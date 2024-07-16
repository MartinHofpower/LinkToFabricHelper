from azure import identity
from itertools import chain, repeat
import pyodbc, struct
import pandas as pd

class CdmSchema:
    _allowed_metadata_readers = ['fabric', 'pyodbc']
    _metadata_tablenames = ['GlobalOptionsetMetadata', 'OptionsetMetadata', 'StateMetadata', 'StatusMetadata', 'TargetMetadata']

    def __init__(self, metadata_connector, sql_endpoint=None, database_name=None, spark_session=None, language_code=None) -> None:
        self._entities = {}
        self._metadata_connector = metadata_connector
        if sql_endpoint is not None and database_name is not None:
            self._connection_string = f"Driver={{ODBC Driver 18 for SQL Server}};Server={sql_endpoint},1433;Database={database_name};Encrypt=Yes;TrustServerCertificate=No"
        if spark_session is not None:
            self._spark_session = spark_session
        if language_code is not None:
            self._language_code = language_code
        else: 
            self._language_code = 1033 # defaults to English
        self._populate_metadata_tables()

    def _populate_metadata_tables(self) -> None:
        """
        This method is a wrapper that populates the metadata tables based on the selected metadata connector.
        If the metadata connector is set to 'fabric', it calls the _populate_metadata_tables_with_fabric() method.
        If the metadata connector is set to 'pyodbc', it calls the _populate_metadata_tables_with_pyodbc() method.
        If the metadata connector is not defined or not one of the allowed metadata readers, it raises a ValueError.
        """
        if self._metadata_connector == 'fabric':
            self._populate_metadata_tables_with_fabric()
        elif self._metadata_connector == 'pyodbc':
            self._populate_metadata_tables_with_pyodbc()
        else:
            raise ValueError(f"Error with metadata_connector setting {self._metadata_connector}. Setting not defined, only one of {self._allowed_metadata_readers} is allowed.")
    
    def _populate_metadata_tables_with_fabric(self) -> None:
        """
        This method populates the metadata tables using the fabric metadata connector.
        It retrieves the table names and column names from the Spark session catalog.
        It also retrieves the global optionsets, optionsets, statecodes, statuscodes, and target metadata from the Spark session.
        """
        #self._tables_metadata = pd.DataFrame({'TABLE_NAME': [table.name for table in self._spark_session.catalog.listTables()]})
        self._tables_metadata = self._spark_session.sql("show tables").selectExpr("tableName as TABLE_NAME").toPandas()
        self._tables_metadata.drop(self._tables_metadata[self._tables_metadata['TABLE_NAME'].isin(self._metadata_tablenames)].index, inplace=True)
        self._columns_metadata = pd.DataFrame(columns=['TABLE_NAME', 'COLUMN_NAME', 'ORDINAL_POSITION'])
        for table_name in self._tables_metadata['TABLE_NAME']:
            #columns_spark = self._spark_session.catalog.listColumns(table_name)
            columns_spark = self._spark_session.sql(f"show columns in {table_name}").selectExpr("col_name as name").collect()
            for cnt, col in enumerate(columns_spark):
                self._columns_metadata = pd.concat([self._columns_metadata, pd.DataFrame({'TABLE_NAME': [table_name], 'COLUMN_NAME': [col.name], 'ORDINAL_POSITION': [cnt]})], ignore_index=True)
        self._global_optionsets_metadata = self._spark_session.sql(f"SELECT EntityName, OptionSetName, Option, LocalizedLabel, GlobalOptionSetName FROM GlobalOptionsetMetadata WHERE LocalizedLabelLanguageCode = {self._language_code}").toPandas()
        self._optionsets_metadata = self._spark_session.sql(f"SELECT EntityName, OptionSetName, Option, LocalizedLabel FROM OptionsetMetadata WHERE LocalizedLabelLanguageCode = {self._language_code}").toPandas()
        self._statecode_metadata = self._spark_session.sql(f"SELECT EntityName, State, LocalizedLabel FROM StateMetadata WHERE LocalizedLabelLanguageCode = {self._language_code}").toPandas()
        self._statuscode_metadata = self._spark_session.sql(f"SELECT EntityName, Status, LocalizedLabel FROM StatusMetadata WHERE LocalizedLabelLanguageCode = {self._language_code}").toPandas()
        self._target_metadata = self._spark_session.sql("SELECT EntityName, AttributeName, ReferencedEntity, ReferencedAttribute FROM TargetMetadata").toPandas()   

    def _populate_metadata_tables_with_pyodbc(self) -> None:
        """
        This method populates the metadata tables using the pyodbc metadata connector.
        It establishes a connection to the SQL Server using the provided connection string.
        It retrieves the table names and column names from the INFORMATION_SCHEMA.
        It also retrieves the global optionsets, optionsets, statecodes, statuscodes, and target metadata from the database.
        """
        credential = identity.InteractiveBrowserCredential() 
        token_object = credential.get_token("https://database.windows.net//.default") 
        token_as_bytes = bytes(token_object.token, "UTF-8") 
        encoded_bytes = bytes(chain.from_iterable(zip(token_as_bytes, repeat(0)))) 
        token_bytes = struct.pack("<i", len(encoded_bytes)) + encoded_bytes 
        attrs_before = {1256: token_bytes}

        connection = pyodbc.connect(self._connection_string, attrs_before=attrs_before)
        self._tables_metadata = pd.read_sql("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = 'dbo' AND TABLE_TYPE = 'BASE TABLE'", connection)
        self._tables_metadata.drop(self._tables_metadata[self._tables_metadata['TABLE_NAME'].isin(self._metadata_tablenames)].index, inplace=True)
        self._columns_metadata = pd.read_sql("SELECT TABLE_NAME, COLUMN_NAME, ORDINAL_POSITION FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'dbo'", connection)
        self._global_optionsets_metadata = pd.read_sql(f"SELECT EntityName, OptionSetName, [Option], LocalizedLabel, GlobalOptionSetName FROM dbo.GlobalOptionsetMetadata WHERE LocalizedLabelLanguageCode = {self._language_code}", connection)
        self._optionsets_metadata = pd.read_sql(f"SELECT EntityName, OptionSetName, [Option], LocalizedLabel FROM dbo.OptionsetMetadata WHERE LocalizedLabelLanguageCode = {self._language_code}", connection)
        self._statecode_metadata = pd.read_sql(f"SELECT EntityName, [State], LocalizedLabel FROM dbo.StateMetadata WHERE LocalizedLabelLanguageCode = {self._language_code}", connection)
        self._statuscode_metadata = pd.read_sql(f"SELECT EntityName, [Status], LocalizedLabel FROM dbo.StatusMetadata WHERE LocalizedLabelLanguageCode = {self._language_code}", connection)
        self._target_metadata = pd.read_sql("SELECT EntityName, AttributeName, ReferencedEntity, ReferencedAttribute FROM dbo.TargetMetadata", connection)
        connection.close()

    # populate schema from metadata tables

    def populate_schema(self) -> None:
        """
        This method populates the schema by iterating over the tables in the metadata and creating entities for each table.
        It also calls the 'upsert_columns' and 'upsert_optionsets' methods for each entity to populate the columns and optionsets.
        """
        for table in self._tables_metadata['TABLE_NAME']:
            entity = Entity(schema=self, entity_name=table)
            self._entities[table] = entity
            entity.upsert_columns()
            entity.upsert_optionsets()

    def create_views(self, output_folder=".", view_prefix='v_', keep_options=False) -> None:
        """
        This method creates views for each entity in the schema.
        It generates SQL code for each entity's view using the 'create_view' method of the entity.
        The SQL code is then written to a file based on the metadata connector.
        Finally, a file containing SQL code for all views is created.
        
        Parameters:
        - output_folder (str): The folder where the view SQL files will be saved. Default is the current directory.
        - view_prefix (str): The prefix to be added to the name of each view. Default is 'v_'.
        - keep_options (bool): Whether to keep the optionsets in the view SQL code. Default is False.
        
        Returns:
        None
        """
        sql_all_views = str()
        for entity in self.entities:
            sql_text = entity.create_view(view_prefix=view_prefix, keep_options=keep_options)
            sql_all_views += sql_text
            if self._metadata_connector == 'fabric':
                with open(f"/lakehouse/default/Files/{output_folder}/{view_prefix}{entity.name}.sql", "w") as text_file:
                    text_file.write(sql_text)
            elif self._metadata_connector == 'pyodbc':
                with open(f"{output_folder}/{view_prefix}{entity.name}.sql", "w") as text_file:
                    text_file.write(sql_text)
        if self._metadata_connector == 'fabric':
                with open(f"/lakehouse/default/Files/{output_folder}/_CREATE_ALL_VIEWS.sql", "w") as text_file:
                    text_file.write(sql_all_views)
        elif self._metadata_connector == 'pyodbc':
            with open(f"{output_folder}/_CREATE_ALL_VIEWS.sql", "w") as text_file:
                text_file.write(sql_all_views)

    # Access methods:

    @property
    def entities(self) -> list: 
        return list(self._entities.values())
    
    def has_entity(self, entity_name) -> bool:
        return entity_name in self._entities.keys()

    def get_entity(self, entity_name):
        if self.has_entity(entity_name=entity_name):
            return self._entities[entity_name]
        else:
            raise KeyError(f"Error: Schema has no entity named '{entity_name}'.")
    
    @property
    def global_optionsets_metadata(self) -> pd.DataFrame:
        return self._global_optionsets_metadata
    
    @property
    def optionsets_metadata(self) -> pd.DataFrame:
        return self._optionsets_metadata
    
    @property
    def statecode_metadata(self) -> pd.DataFrame:
        return self._statecode_metadata
    
    @property
    def statuscode_metadata(self) -> pd.DataFrame:
        return self._statuscode_metadata
    
    @property
    def target_metadata(self) -> pd.DataFrame:
        return self._target_metadata
    
    @property
    def columns_metadata(self) -> pd.DataFrame:
        return self._columns_metadata
    
    @property
    def language_code(self) -> int:
        return self._language_code
    

class Entity:
    def __init__(self, schema, entity_name) -> None:
        self._schema = schema
        self._name = entity_name
        self._columns = {} 
        self._optionsets = {} 

    @property
    def name(self) -> str:
        """
        Get the name of the entity.
        
        Returns:
        str: The name of the entity.
        """
        return self._name
    
    @property
    def schema(self):
        """
        Get the schema that the entity belongs to.
        
        Returns:
        CdmSchema: The schema that the entity belongs to.
        """
        return self._schema

    def upsert_columns(self) -> None:
        """
        Upsert the columns of the entity.
        This method populates the columns dictionary of the entity by iterating over the columns metadata of the schema.
        
        Returns:
        None
        """
        for index, row in self.schema.columns_metadata[self.schema.columns_metadata['TABLE_NAME'] == self.name].iterrows():
            self._columns[row['COLUMN_NAME']] = Column(entity=self, column_name=row['COLUMN_NAME'], ordinal_position=row['ORDINAL_POSITION'])

    @property
    def columns(self) -> list: 
        """
        Get the columns of the entity.
        
        Returns:
        list: The list of columns of the entity.
        """
        return list(self._columns.values())
    
    def has_column(self, column_name) -> bool:
        """
        Check if the entity has a column with the given name.
        
        Parameters:
        - column_name (str): The name of the column.
        
        Returns:
        bool: True if the entity has a column with the given name, False otherwise.
        """
        return column_name in self._columns.keys()
    
    def get_column(self, column_name):
        """
        Get the column with the given name.
        
        Parameters:
        - column_name (str): The name of the column.
        
        Returns:
        Column: The column with the given name.
        
        Raises:
        KeyError: If the entity has no column with the given name.
        """
        if self.has_column(column_name=column_name):
            return self._columns[column_name]
        else:
            raise KeyError(f"Error: Entity {self.name} has no column named '{column_name}'.")
    
    def upsert_optionsets(self) -> None:
        """
        Upsert the optionsets of the entity.
        This method populates the optionsets dictionary of the entity based on the columns metadata and global/optionsets metadata of the schema.
        
        Returns:
        None
        """
        if self.has_column(column_name='statecode'):
            self._optionsets['statecode'] = Optionset(name='statecode', optionset_table="StateMetadata", entity=self, instance=self.schema.statecode_metadata[self.schema.statecode_metadata['EntityName'] == self.name].rename(columns={'State': 'Option'}))
        if self.has_column(column_name='statuscode'): 
            self._optionsets['statuscode'] = Optionset(name='statuscode', optionset_table="StatusMetadata", entity=self, instance=self.schema.statuscode_metadata[self.schema.statuscode_metadata['EntityName'] == self.name].rename(columns={'Status': 'Option'}))
        for column in self.columns:
            if column.name in self.schema.global_optionsets_metadata[self.schema.global_optionsets_metadata['EntityName'] == self.name]['OptionSetName'].tolist():
                instance = self.schema.global_optionsets_metadata[(self.schema.global_optionsets_metadata['EntityName'] == self.name) & (self.schema.global_optionsets_metadata['OptionSetName'] == column.name)]
                self._optionsets[column.name] = Optionset(name=column.name, optionset_table="GlobalOptionsetMetadata", entity=self, instance=instance)
            if column.name in self.schema.optionsets_metadata[self.schema.optionsets_metadata['EntityName'] == self.name]['OptionSetName'].tolist():
                instance = self.schema.optionsets_metadata[(self.schema.optionsets_metadata['EntityName'] == self.name) & (self.schema.optionsets_metadata['OptionSetName'] == column.name)]
                self._optionsets[column.name] = Optionset(name=column.name, optionset_table="OptionsetMetadata", entity=self, instance=instance)
            
    @property
    def optionsets(self) -> list: 
        """
        Get the optionsets of the entity.
        
        Returns:
        list: The list of optionsets of the entity.
        """
        return list(self._optionsets.values())
    
    def has_optionset(self, optionset_name) -> bool:
        """
        Check if the entity has an optionset with the given name.
        
        Parameters:
        - optionset_name (str): The name of the optionset.
        
        Returns:
        bool: True if the entity has an optionset with the given name, False otherwise.
        """
        return optionset_name in self._optionsets.keys()
    
    def get_optionset(self, optionset_name):
        """
        Get the optionset with the given name.
        
        Parameters:
        - optionset_name (str): The name of the optionset.
        
        Returns:
        Optionset: The optionset with the given name.
        
        Raises:
        KeyError: If the entity has no optionset with the given name.
        """
        if self.has_optionset(optionset_name=optionset_name):
            return self._optionsets[optionset_name]
        else:
            raise KeyError(f"Error: Entity {self.name} has no optionset named '{optionset_name}'.")
    
    def create_view(self, view_prefix, keep_options) -> str:
        """
        Create the SQL code for the view of the entity.
        
        Parameters:
        - view_prefix (str): The prefix to be added to the name of the view.
        - keep_options (bool): Whether to keep the optionsets in the view SQL code.
        
        Returns:
        str: The SQL code for the view of the entity.
        """
        pre_from = f"CREATE OR ALTER VIEW {view_prefix}{self.name} \n AS \n SELECT "
        post_from = f"FROM {self.name} AS tab \n"
        if self.schema._metadata_connector == 'fabric':	
            left_bracket = ""
            right_bracket = ""
        else:
            left_bracket = "["
            right_bracket = "]"
        ordered_columns = dict(sorted({column.ordinal_position: column.name for column in self.columns}.items()))
        for column_order, column_name in ordered_columns.items():
            if column_order == 1: # always "Id" -> no optionset possible
                pre_from += f"tab.{left_bracket}{column_name}{right_bracket} \n"
            else:
                if self.has_optionset(column_name):
                    optionset = self.get_optionset(column_name)
                    if keep_options:
                        pre_from += f"       ,tab.{left_bracket}{optionset.name}{right_bracket} AS {left_bracket}{optionset.name}_option{right_bracket} \n"
                        col_name_suffix = "_label"
                    else:
                        col_name_suffix = ""
                    pre_from += f"       ,col{column_order}.{left_bracket}LocalizedLabel{right_bracket} AS {left_bracket}{optionset.name}{col_name_suffix}{right_bracket}\n"
                    post_from += f" LEFT JOIN {optionset.optionset_table} AS col{column_order} \n"
                    post_from += f"  ON tab.{left_bracket}{column_name}{right_bracket} = col{column_order}.{left_bracket}{optionset.option_qualifier}{right_bracket} \n"
                    post_from += f" AND col{column_order}.EntityName = '{self.name}' \n"
                    post_from += f" AND col{column_order}.LocalizedLabelLanguageCode = {self.schema.language_code} \n" 
                    if optionset.option_qualifier not in ["State", "Status"]:
                        post_from += f" AND col{column_order}.OptionSetName = '{column_name}' \n"
                else:
                    pre_from += f"       ,tab.{left_bracket}{column_name}{right_bracket} \n"
        return pre_from + post_from + "GO \n \n"


class Column:
    def __init__(self, entity, column_name, ordinal_position) -> None:
        self._entity = entity
        self._name = column_name
        self._ordinal_position = ordinal_position

    @property
    def entity(self) -> Entity:
        """
        Get the entity that the column belongs to.
        
        Returns:
        Entity: The entity that the column belongs to.
        """
        return self._entity
    
    @property
    def name(self) -> str:
        """
        Get the name of the column.
        
        Returns:
        str: The name of the column.
        """
        return self._name
    
    @property
    def ordinal_position(self) -> int:
        """
        Get the ordinal position of the column.
        
        Returns:
        int: The ordinal position of the column.
        """
        return self._ordinal_position


class Optionset:
    def __init__(self, name, optionset_table, entity, instance) -> None:
        self._name = name
        self._optionset_table = optionset_table
        if optionset_table == "StateMetadata":
            self._option_qualifier = "State"
        elif optionset_table == "StatusMetadata":
            self._option_qualifier = "Status"
        else: 
            self._option_qualifier = "Option"
        self._entity = entity
        self._instance = instance
        self._options_dict = {}
        self._populate_options_dict()

    def _populate_options_dict(self) -> None:
        """
        Populate the options dictionary of the optionset.
        
        Returns:
        None
        """
        for index, row in self._instance.iterrows():
            self._options_dict[row['Option']] = row['LocalizedLabel']

    @property
    def entity(self) -> Entity:
        """
        Get the entity that the optionset belongs to.
        
        Returns:
        Entity: The entity that the optionset belongs to.
        """
        return self._entity
    
    @property
    def name(self) -> str:
        """
        Get the name of the optionset.
        
        Returns:
        str: The name of the optionset.
        """
        return self._name
    
    @property
    def options_dict(self) -> dict:
        """
        Get the options dictionary of the optionset.
        
        Returns:
        dict: The options dictionary of the optionset.
        """
        return self._options_dict
    
    @property
    def optionset_table(self) -> str:
        """
        Get the optionset table of the optionset.
        
        Returns:
        str: The optionset table of the optionset.
        """
        return self._optionset_table

    @property
    def option_qualifier(self) -> str:
        """
        Get the option qualifier of the optionset.
        
        Returns:
        str: The option qualifier of the optionset.
        """
        return self._option_qualifier
