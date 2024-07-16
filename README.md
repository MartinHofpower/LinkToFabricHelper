# LinkToFabricHelper

[![PyPI Latest Release](https://img.shields.io/pypi/v/linkToFabricHelper.svg)](https://pypi.org/project/LinkToFabricHelper/) 

Disclaimer: Since the package is in an early stage of development it is not recommended to use it in production-environments. 

This package is designed to help developers of solutions im Microsoft Fabric that use dataverse's functionality "Link to Microsoft Fabric" to handle the cdm-like structure of the data. 

### Common Data Model 

For more information on the "Common Data Model" (CDM) see for example the official documentation of Microsoft on [Microsoft Learn](https://learn.microsoft.com/en-us/common-data-model/). 

## How to use LinkToFabricHelper

### Utilize CDM-Schema

The exported tables from dataverse come with referenced optionssets for lots of columns. This comes with the need to dereference this columns somewhen to present the data to business users. 

This package provides the functionality to read the metadata provided by the "Link to Microsoft Fabric" functionality within the lakehouse and utilize it in views so that business users get an easy interface to access their data in a raw format if required and give data engineers the possibility to easily transform the data in later stages. 

Turn this: 
![Table with options](docs/img/001_TableWithOptions.png)
Into that: 
![View with labels](docs/img/002_ViewWithLabels.png)

The package is designed to work when called from within a Fabric notebook so that such an update of views can run e.g. after a dataverse release and thus a possible schema change. But be aware that there is currently no possibility to create views in the sql endpoint directly out of a notebook (inofficially announced in a blog for later in 2024) so currently the created script needs to be executed manually via the sql endpoint. 

For a detailed explanation of how to use the package to create these views see [the detailed documentation here.](docs/CreateConsumptionViews.md)

#### Local execution

It is also possible to connect to the sql endpoint directly and retrieve the metadata from there. Since the vision of this package is a direct execution within a Fabric notebook and needs someone executing it on a local machine this is not the recommended approach. 
Nevertheless it is nice to have this possibility for debugging and development so an exemplary call is given in [localexecution.py](localexecution.py) which needs SQL_ENDPOINT (sql endpoint connection string from Fabric lakehouse) and DATABASE_NAME (name of the lakehouse in Fabric) defined in a seperate script. 
