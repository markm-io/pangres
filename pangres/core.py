#!/usr/bin/env python
# coding: utf-8
# +
"""
This module contains the functions of pangres
that will be directly exposed to its users.
"""
import pandas as pd
from sqlalchemy.engine.base import Connectable, Engine
from typing import Optional, Union

# local imports
from pangres.executor import Executor


# -

# # upsert

def upsert(engine:Engine,
           df:pd.DataFrame,
           table_name:str,
           if_row_exists:str,
           schema:Optional[str]=None,
           create_schema:bool=False,
           create_table:bool=True,
           add_new_columns:bool=False,
           adapt_dtype_of_empty_db_columns:bool=False,
           chunksize:int=10000,
           dtype:Union[dict,None]=None,
           yield_chunks:bool=False):
    """
    Insert updates/ignores a pandas DataFrame into a SQL table (or
    creates a SQL table from the DataFrame if it does not exist).

    This index of the DataFrame must be the primary key or a unique key
    (can be a unique constraint with multiple columns too) of the SQL
    table and meet the following conditions:
    1. The index must be unique.
    2. All levels of the index have to be named.
    3. The index cannot contain any null value except for MySQL where
    rows with null in indices will be skipped and warnings will be raised.

    **GOTCHAS**:

    Please head over to https://github.com/ThibTrip/pangres/#Gotchas-and-caveats
    or read pangres/README.md.

    Notes
    -----
    It is recommanded to use this function with big batches of data
    as there is quite the overhead. Setting the arguments create_schema,
    add_new_columns and adapt_dtype_of_empty_db_columns to False should
    drastically reduce the overhead if you do not need such features.

    Parameters
    ----------
    engine : sqlalchemy.engine.base.Engine
        See https://docs.sqlalchemy.org/en/latest/core/engines.html
    df : pd.DataFrame
        See https://pandas.pydata.org/pandas-docs/stable/user_guide/10min.html
    table_name : str
        Name of the SQL table
    if_row_exists : {'ignore', 'update'}
        Behavior if a row exists in the SQL table.
        Irrelevant if the SQL table does not exist already.
        For both 'ignore' and 'update' rows with new primary/unique
        key values are inserted.

        * 'ignore': rows for which primary/unique keys exist in the SQL
        table are skipped
        * 'update': rows for which primary/unique keys exist in the SQL
        table are updated (with the columns available in the pandas
        DataFrame)
    schema : str or None, default None
        Name of the SQL schema that contains or will contain the table
        For postgres if it is None it will default to "public".
        For MySQL and SQlite the schema should be None since
        those SQL flavors do not have this system.
    create_schema : bool, default False
        If True the schema is created if it does not exist
    create_table : bool, default True
        If True the table is created if it does not exist
    add_new_columns : bool, default False
        If True adds columns present in the DataFrame that
        are not in the SQL table.
    adapt_dtype_of_empty_db_columns : bool, default False
        If True looks for columns that have no data in the
        SQL table but have data in the DataFrame;
        if those columns have datatypes that do not match
        (e.g. "TEXT" in the SQL table and "int64" in the DataFrame)
        then they are altered in the SQL table.
        Data type conversion must be supported by the SQL flavor!
        E.g. for Postgres converting from BOOLEAN to TIMESTAMP
        will not work even if the column is empty.
    chunksize : int
        Number of rows to insert at once.
        Please note that for SQlite a maximum of 999 parameters
        per queries means that the chunksize will be automatically
        reduced to math.floor(999/nb_columns) where nb_columns is
        the number of columns + index levels in the DataFrame.
    dtype : None or dict {str:SQL_TYPE}, default None
        Similar to pd.to_sql dtype argument.
        This is especially useful for MySQL where the length of
        primary keys with text has to be provided (see Examples)
    yield_chunks : bool, default False
        If True gives back an sqlalchemy object
        (sqlalchemy.engine.cursor.LegacyCursorResult)
        at each chunk with which you can for instance count rows.

    Raises
    ------
    pangres.exceptions.HasNoSchemaSystemException
        When `create_schema` is True but the SQL flavor of given
        engine has no schema system (AFAIK only PostgreSQL has a
        schema system)
    pangres.exceptions.BadColumnNamesException
        When column names are incompatible with the SQL driver
        (e.g. psycopg2 does not accept "(" in a column name)
    pangres.exceptions.UnnamedIndexLevelsException
        When some of the index levels of the df are not named
    pangres.exceptions.DuplicateValuesInIndexException
        When any entry in the df's index is duplicated
    pangres.exceptions.DuplicateLabelsException
        When any name across the df's index/columns appears more than once
    pangres.exceptions.MissingIndexLevelInSqlException
        When `add_new_columns` is True but one of the columns missing
        in the SQL table is actually part of the df's index

    Examples
    --------
    #### 1. Workflow example

    ##### 1.1. Creating a SQL table
    >>> import pandas as pd
    >>> from pangres import upsert, DocsExampleTable
    >>> from sqlalchemy import create_engine, text, VARCHAR
    >>>
    >>> # create a SQLalchemy engine
    >>> engine = create_engine("sqlite://")
    >>>
    >>> # this is necessary if you want to test with MySQL
    >>> # instead of SQlite or Postgres because MySQL needs
    >>> # to have a definite limit for text primary keys/indices
    >>> dtype = {'full_name':VARCHAR(50)}
    >>>
    >>> # get or create a pandas DataFrame
    >>> # for our example full_name is the index
    >>> # and will thus be used as primary key
    >>> df = DocsExampleTable.df
    >>> print(df.to_markdown()) # to_markdown exists since pandas v1
    | full_name     | likes_sport   | updated                   |   size_in_meters |
    |:--------------|:--------------|:--------------------------|-----------------:|
    | John Rambo    | True          | 2020-02-01 00:00:00+00:00 |             1.77 |
    | The Rock      | True          | 2020-04-01 00:00:00+00:00 |             1.96 |
    | John Travolta | False         | NaT                       |           nan    |

    >>> # create SQL table
    >>> # it does not matter if if_row_exists is set
    >>> # to "update" or "ignore" for table creation
    >>> upsert(engine=engine,
    ...        df=df,
    ...        table_name='example',
    ...        if_row_exists='update',
    ...        dtype=dtype)

    ##### 1.2. Updating the SQL table we created with if_row_exists='update'
    >>> new_df = DocsExampleTable.new_df
    >>> print(new_df.to_markdown())
    | full_name             | likes_sport   | updated                   |   size_in_meters |
    |:----------------------|:--------------|:--------------------------|-----------------:|
    | John Travolta         | True          | 2020-04-04 00:00:00+00:00 |             1.88 |
    | Arnold Schwarzenegger | True          | NaT                       |             1.88 |

    >>> # insert update using our new data
    >>> # we know the table already exists so we can pass `create_table=False`
    >>> # to skip the table existence check and gain a little time
    >>> # note that if the table did not exist we would get an error!
    >>> upsert(engine=engine,
    ...        df=new_df,
    ...        table_name='example',
    ...        if_row_exists='update',
    ...        dtype=dtype,
    ...        create_table=False)
    >>> 
    >>> # Now we read from the database to check what we got and as you can see
    >>> # John Travolta was updated and Arnold Schwarzenegger was added!
    >>> with engine.connect() as connection:
    ...     query = text('SELECT * FROM example')
    ...     print(pd.read_sql(query, con=connection, index_col='full_name')
    ...           .astype({'likes_sport':bool}).to_markdown())
    | full_name             | likes_sport   | updated                    |   size_in_meters |
    |:----------------------|:--------------|:---------------------------|-----------------:|
    | John Rambo            | True          | 2020-02-01 00:00:00.000000 |             1.77 |
    | The Rock              | True          | 2020-04-01 00:00:00.000000 |             1.96 |
    | John Travolta         | True          | 2020-04-04 00:00:00.000000 |             1.88 |
    | Arnold Schwarzenegger | True          |                            |             1.88 |

    ##### 1.3. Updating the SQL table with if_row_exists='ignore'
    >>> new_df2 = DocsExampleTable.new_df2
    >>> print(new_df2.to_markdown())
    | full_name     | likes_sport   | updated   |   size_in_meters |
    |:--------------|:--------------|:----------|-----------------:|
    | John Travolta | True          | NaT       |             2.5  |
    | John Cena     | True          | NaT       |             1.84 |

    >>> upsert(engine=engine,
    ...        df=new_df2,
    ...        table_name='example',
    ...        if_row_exists='ignore',
    ...        dtype=dtype,
    ...        create_table=False)
    >>>
    >>>
    >>> # Now we read from the database to check what we got and as you can see
    >>> # John Travolta was NOT updated and John Cena was added!
    >>> with engine.connect() as connection:
    ...     query = text('SELECT * FROM example')
    ...     print(pd.read_sql(query, con=connection, index_col='full_name')
    ...           .astype({'likes_sport':bool}).to_markdown())
    | full_name             | likes_sport   | updated                    |   size_in_meters |
    |:----------------------|:--------------|:---------------------------|-----------------:|
    | John Rambo            | True          | 2020-02-01 00:00:00.000000 |             1.77 |
    | The Rock              | True          | 2020-04-01 00:00:00.000000 |             1.96 |
    | John Travolta         | True          | 2020-04-04 00:00:00.000000 |             1.88 |
    | Arnold Schwarzenegger | True          |                            |             1.88 |
    | John Cena             | True          |                            |             1.84 |

    #### 2. Example for getting information on upserted chunks (parameter `yield_chunks` == True)
    >>> import pandas as pd
    >>> from pangres import upsert, DocsExampleTable
    >>> from sqlalchemy import create_engine, VARCHAR
    >>>
    >>> # config
    >>> engine = create_engine("sqlite://")
    >>> chunksize = 2
    >>>
    >>> # get a DataFrame from somwhere
    >>> df = DocsExampleTable.df
    >>> print(df.to_markdown())
    | full_name     | likes_sport   | updated                   |   size_in_meters |
    |:--------------|:--------------|:--------------------------|-----------------:|
    | John Rambo    | True          | 2020-02-01 00:00:00+00:00 |             1.77 |
    | The Rock      | True          | 2020-04-01 00:00:00+00:00 |             1.96 |
    | John Travolta | False         | NaT                       |           nan    |

    >>>
    >>> # upsert in chunks of size `chunksize` and get
    >>> # back the number of rows updated for each chunk
    >>> iterator = upsert(engine=engine, df=df, table_name='test_row_count',
    ...                   chunksize=chunksize, if_row_exists='update',
    ...                   yield_chunks=True)
    >>> for result in iterator:
    ...     print(f'{result.rowcount} row(s) updated')
    2 row(s) updated
    1 row(s) updated
    """
    # verify arguments
    if if_row_exists not in ('ignore', 'update'):
        raise ValueError('if_row_exists must be "ignore" or "update"')

    executor = Executor(df=df, table_name=table_name, schema=schema, create_schema=create_schema,
                        create_table=create_table, dtype=dtype, add_new_columns=add_new_columns,
                        adapt_dtype_of_empty_db_columns=adapt_dtype_of_empty_db_columns)
    if not yield_chunks:
        executor.execute(connectable=engine, if_row_exists=if_row_exists, chunksize=chunksize)
    else:
        return executor.execute_yield(connectable=engine, if_row_exists=if_row_exists, chunksize=chunksize)


# # upsert_future

def upsert_future(con:Connectable,
                  df:pd.DataFrame,
                  table_name:str,
                  if_row_exists:str,
                  schema:Optional[str]=None,
                  create_schema:bool=False,
                  create_table:bool=True,
                  add_new_columns:bool=False,
                  adapt_dtype_of_empty_db_columns:bool=False,
                  chunksize:int=10000,
                  dtype:Union[dict,None]=None,
                  yield_chunks:bool=False):
    """
    Insert updates/ignores a pandas DataFrame into a SQL table (or
    creates a SQL table from the DataFrame if it does not exist).

    This index of the DataFrame must be the primary key or a unique key
    (can be a unique constraint with multiple columns too) of the SQL
    table and meet the following conditions:
    1. The index must be unique.
    2. All levels of the index have to be named.
    3. The index cannot contain any null value except for MySQL where
    rows with null in indices will be skipped and warnings will be raised.

    **GOTCHAS**:

    Please head over to https://github.com/ThibTrip/pangres/#Gotchas-and-caveats
    or read pangres/README.md.

    **IMPORTANT NOTES ON CONNECTIONS AND TRANSACTIONS**:

    * If an Engine object (sqlalchemy.engine.base.Engine) is given for the parameter `con`:
    
    We will create a connection and a transaction and handle everything (commit|rollback
    and closing both the connection and transaction).

    * If a connection object (sqlalchemy.engine.base.Connection) is given for the parameter `con`:

    We will not close the connection (so that you may reuse it later). You will have to close
    it yourself!
    We will not create or handle transactions. This is for allowing users to make commit-as-you-go
    workflows.

    See examples in notebook https://github.com/ThibTrip/pangres/blob/master/demos/transaction_control.ipynb

    Notes
    -----
    It is recommanded to use this function with big batches of data
    as there is quite the overhead. Setting the arguments create_schema,
    add_new_columns and adapt_dtype_of_empty_db_columns to False should
    drastically reduce the overhead if you do not need such features.

    Parameters
    ----------
    con : sqlalchemy.engine.base.Engine or sqlalchemy.engine.base.Connection
        See https://docs.sqlalchemy.org/en/latest/core/engines.html
    df : pd.DataFrame
        See https://pandas.pydata.org/pandas-docs/stable/user_guide/10min.html
    table_name : str
        Name of the SQL table
    if_row_exists : {'ignore', 'update'}
        Behavior if a row exists in the SQL table.
        Irrelevant if the SQL table does not exist already.
        For both 'ignore' and 'update' rows with new primary/unique
        key values are inserted.

        * 'ignore': rows for which primary/unique keys exist in the SQL
        table are skipped
        * 'update': rows for which primary/unique keys exist in the SQL
        table are updated (with the columns available in the pandas
        DataFrame)
    schema : str or None, default None
        Name of the SQL schema that contains or will contain the table
        For postgres if it is None it will default to "public".
        For MySQL and SQlite the schema should be None since
        those SQL flavors do not have this system.
    create_schema : bool, default False
        If True the schema is created if it does not exist
    create_table : bool, default True
        If True the table is created if it does not exist
    add_new_columns : bool, default False
        If True adds columns present in the DataFrame that
        are not in the SQL table.
    adapt_dtype_of_empty_db_columns : bool, default False
        If True looks for columns that have no data in the
        SQL table but have data in the DataFrame;
        if those columns have datatypes that do not match
        (e.g. "TEXT" in the SQL table and "int64" in the DataFrame)
        then they are altered in the SQL table.
        Data type conversion must be supported by the SQL flavor!
        E.g. for Postgres converting from BOOLEAN to TIMESTAMP
        will not work even if the column is empty.
    chunksize : int
        Number of rows to insert at once.
        Please note that for SQlite a maximum of 999 parameters
        per queries means that the chunksize will be automatically
        reduced to math.floor(999/nb_columns) where nb_columns is
        the number of columns + index levels in the DataFrame.
    dtype : None or dict {str:SQL_TYPE}, default None
        Similar to pd.to_sql dtype argument.
        This is especially useful for MySQL where the length of
        primary keys with text has to be provided (see Examples)
    yield_chunks : bool, default False
        If True gives back an sqlalchemy object
        (sqlalchemy.engine.cursor.LegacyCursorResult)
        at each chunk with which you can for instance count rows.

    Raises
    ------
    pangres.exceptions.HasNoSchemaSystemException
        When `create_schema` is True but the SQL flavor of given
        engine has no schema system (AFAIK only PostgreSQL has a
        schema system)
    pangres.exceptions.BadColumnNamesException
        When column names are incompatible with the SQL driver
        (e.g. psycopg2 does not accept "(" in a column name)
    pangres.exceptions.UnnamedIndexLevelsException
        When some of the index levels of the df are not named
    pangres.exceptions.DuplicateValuesInIndexException
        When any entry in the df's index is duplicated
    pangres.exceptions.DuplicateLabelsException
        When any name across the df's index/columns appears more than once
    pangres.exceptions.MissingIndexLevelInSqlException
        When `add_new_columns` is True but one of the columns missing
        in the SQL table is actually part of the df's index

    Examples
    --------
    #### 1. Workflow example

    ##### 1.1. Creating a SQL table
    >>> import pandas as pd
    >>> from pangres import upsert_future, DocsExampleTable
    >>> from sqlalchemy import create_engine, text, VARCHAR
    >>>
    >>> # create a SQLalchemy engine
    >>> engine = create_engine("sqlite://")
    >>>
    >>> # this is necessary if you want to test with MySQL
    >>> # instead of SQlite or Postgres because MySQL needs
    >>> # to have a definite limit for text primary keys/indices
    >>> dtype = {'full_name':VARCHAR(50)}
    >>>
    >>> # get or create a pandas DataFrame
    >>> # for our example full_name is the index
    >>> # and will thus be used as primary key
    >>> df = DocsExampleTable.df
    >>> print(df.to_markdown()) # to_markdown exists since pandas v1
    | full_name     | likes_sport   | updated                   |   size_in_meters |
    |:--------------|:--------------|:--------------------------|-----------------:|
    | John Rambo    | True          | 2020-02-01 00:00:00+00:00 |             1.77 |
    | The Rock      | True          | 2020-04-01 00:00:00+00:00 |             1.96 |
    | John Travolta | False         | NaT                       |           nan    |

    >>> # create SQL table
    >>> # it does not matter if if_row_exists is set
    >>> # to "update" or "ignore" for table creation
    >>> upsert_future(con=engine,
    ...               df=df,
    ...               table_name='example',
    ...               if_row_exists='update',
    ...               dtype=dtype)

    >>> # alternative for the statement above using a connection
    >>> # instead of an engine (the same logic can be applied for
    >>> # all usages of the `upsert_future` function below
    >>> with engine.connect() as con:
    ...     upsert_future(con=con, df=df, table_name='example',
    ...                   if_row_exists='update', dtype=dtype)
    ...     # con.commit() # IMPORTANT! required for sqlalchemy >= 2.0

    ##### 1.2. Updating the SQL table we created with if_row_exists='update'
    >>> new_df = DocsExampleTable.new_df
    >>> print(new_df.to_markdown())
    | full_name             | likes_sport   | updated                   |   size_in_meters |
    |:----------------------|:--------------|:--------------------------|-----------------:|
    | John Travolta         | True          | 2020-04-04 00:00:00+00:00 |             1.88 |
    | Arnold Schwarzenegger | True          | NaT                       |             1.88 |

    >>> # insert update using our new data
    >>> # we know the table already exists so we can pass `create_table=False`
    >>> # to skip the table existence check and gain a little time
    >>> # note that if the table did not exist we would get an error!
    >>> upsert_future(con=engine,
    ...               df=new_df,
    ...               table_name='example',
    ...               if_row_exists='update',
    ...               dtype=dtype,
    ...               create_table=False)
    >>> 
    >>> # Now we read from the database to check what we got and as you can see
    >>> # John Travolta was updated and Arnold Schwarzenegger was added!
    >>> with engine.connect() as connection:
    ...     query = text('SELECT * FROM example')
    ...     print(pd.read_sql(query, con=connection, index_col='full_name')
    ...           .astype({'likes_sport':bool}).to_markdown())
    | full_name             | likes_sport   | updated                    |   size_in_meters |
    |:----------------------|:--------------|:---------------------------|-----------------:|
    | John Rambo            | True          | 2020-02-01 00:00:00.000000 |             1.77 |
    | The Rock              | True          | 2020-04-01 00:00:00.000000 |             1.96 |
    | John Travolta         | True          | 2020-04-04 00:00:00.000000 |             1.88 |
    | Arnold Schwarzenegger | True          |                            |             1.88 |

    ##### 1.3. Updating the SQL table with if_row_exists='ignore'
    >>> new_df2 = DocsExampleTable.new_df2
    >>> print(new_df2.to_markdown())
    | full_name     | likes_sport   | updated   |   size_in_meters |
    |:--------------|:--------------|:----------|-----------------:|
    | John Travolta | True          | NaT       |             2.5  |
    | John Cena     | True          | NaT       |             1.84 |

    >>> upsert_future(con=engine,
    ...               df=new_df2,
    ...               table_name='example',
    ...               if_row_exists='ignore',
    ...               dtype=dtype,
    ...               create_table=False)
    >>>
    >>>
    >>> # Now we read from the database to check what we got and as you can see
    >>> # John Travolta was NOT updated and John Cena was added!
    >>> with engine.connect() as connection:
    ...     query = text('SELECT * FROM example')
    ...     print(pd.read_sql(query, con=connection, index_col='full_name')
    ...           .astype({'likes_sport':bool}).to_markdown())
    | full_name             | likes_sport   | updated                    |   size_in_meters |
    |:----------------------|:--------------|:---------------------------|-----------------:|
    | John Rambo            | True          | 2020-02-01 00:00:00.000000 |             1.77 |
    | The Rock              | True          | 2020-04-01 00:00:00.000000 |             1.96 |
    | John Travolta         | True          | 2020-04-04 00:00:00.000000 |             1.88 |
    | Arnold Schwarzenegger | True          |                            |             1.88 |
    | John Cena             | True          |                            |             1.84 |

    #### 2. Example for getting information on upserted chunks (parameter `yield_chunks` == True)
    >>> import pandas as pd
    >>> from pangres import upsert_future, DocsExampleTable
    >>> from sqlalchemy import create_engine, VARCHAR
    >>>
    >>> # config
    >>> engine = create_engine("sqlite://")
    >>> chunksize = 2
    >>>
    >>> # get a DataFrame from somwhere
    >>> df = DocsExampleTable.df
    >>> print(df.to_markdown())
    | full_name     | likes_sport   | updated                   |   size_in_meters |
    |:--------------|:--------------|:--------------------------|-----------------:|
    | John Rambo    | True          | 2020-02-01 00:00:00+00:00 |             1.77 |
    | The Rock      | True          | 2020-04-01 00:00:00+00:00 |             1.96 |
    | John Travolta | False         | NaT                       |           nan    |

    >>>
    >>> # upsert in chunks of size `chunksize` and get
    >>> # back the number of rows updated for each chunk
    >>> iterator = upsert_future(con=engine, df=df, table_name='test_row_count',
    ...                          chunksize=chunksize, if_row_exists='update',
    ...                          yield_chunks=True)
    >>> for result in iterator:
    ...     print(f'{result.rowcount} row(s) updated')
    2 row(s) updated
    1 row(s) updated
    """
    # verify arguments
    if if_row_exists not in ('ignore', 'update'):
        raise ValueError('if_row_exists must be "ignore" or "update"')

    executor = Executor(df=df, table_name=table_name, schema=schema, create_schema=create_schema,
                        create_table=create_table, dtype=dtype, add_new_columns=add_new_columns,
                        adapt_dtype_of_empty_db_columns=adapt_dtype_of_empty_db_columns)
    if not yield_chunks:
        executor.execute(connectable=con, if_row_exists=if_row_exists, chunksize=chunksize)
    else:
        return executor.execute_yield(connectable=con, if_row_exists=if_row_exists, chunksize=chunksize)
