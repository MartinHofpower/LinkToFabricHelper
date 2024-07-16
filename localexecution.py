from src.LinkToFabricHelper import CdmSchema as cdmschema
import connection_secrets # local file with SQL_ENDPOINT and DATABASE_NAME
SQL_ENDPOINT = connection_secrets.SQL_ENDPOINT
DATABASE_NAME = connection_secrets.DATABASE_NAME

# Package can run either from local machine or within Fabric
# -> if run in fabric use metadata_connector = 'fabric' and set SparkSession
# -> if run from local machine use metadata_connector = 'pyodbc' and set corresponding properties
language_code = 1031
ltfh = cdmschema.CdmSchema(metadata_connector='pyodbc', 
                           sql_endpoint=SQL_ENDPOINT, 
                           database_name=DATABASE_NAME,
                           language_code=language_code)

ltfh.populate_schema()

ltfh.create_views(output_folder="out", view_prefix="v_entity_", keep_options=True)