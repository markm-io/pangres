#!/usr/bin/env python
# coding: utf-8
import pandas as pd
import pytest
from sqlalchemy import VARCHAR, text
from pangres.examples import _TestsExampleTable
from pangres.exceptions import HasNoSchemaSystemException
from pangres.helpers import PandasSpecialEngine
from pangres.tests.conftest import AutoDropTableContext


# # Test methods and attributes

# +
def test_repr(engine, schema):
    dummy_df = pd.DataFrame(index=pd.Index(data=[0], name='id'))
    pse = PandasSpecialEngine(engine=engine, schema=schema, table_name='x', df=dummy_df)
    # make sure it is printable without errors
    print(pse)
    # test some strings we expect to find in the repr
    txt = str(pse)
    for s in ('PandasSpecialEngine', 'id ', 'hexid', 'connection',
              'schema', 'table', 'SQLalchemy table model'):
        assert s in txt

def test_table_attr(engine, schema):
    # generate a somewhat complex table model via the _TestsExampleTable class
    df = _TestsExampleTable.create_example_df(nb_rows=10)
    table_name = 'test_table_attr'
    pse = PandasSpecialEngine(engine=engine, schema=schema, table_name=table_name, df=df)
    # make sure columns and table name match
    expected_cols = list(df.index.names) + df.columns.tolist()
    assert all((col in pse.table.columns for col in expected_cols))
    assert pse.table.name == table_name


def test_schema_creation(engine, schema):
    # overwrite schema
    schema = 'pangres_create_schema_test'
    # local helpers
    def drop_schema(connection):        
        connection.execute(text(f'DROP SCHEMA IF EXISTS {schema};'))
        if hasattr(connection, 'commit'):
            connection.commit()
    # drop schema then try to create from a PandasSpecialEngine instance
    ## PandasSpecialEngine requires a df even though it is irrelevant here
    dummy_df = pd.DataFrame(index=pd.Index(data=[0], name='id'))
    with engine.connect() as connection:
        try:
            pse = PandasSpecialEngine(engine=engine, schema=schema, table_name='x', df=dummy_df)
            # this should raise HasNoSchemaSystemException if we are not on a postgres engine
            assert not pse.schema_exists(connection=connection)
            drop_schema(connection)
            pse.create_schema_if_not_exists()
            assert pse.schema_exists(connection=connection)
        except Exception as e:
            # if it is postgres then schema creation should work, otherwise
            # we should get HasNoSchemaSystemException
            if pse._db_type == 'postgres' or not isinstance(e, HasNoSchemaSystemException):
                raise e
        finally:
            if pse._db_type == 'postgres':
                drop_schema(connection)


def test_table_creation(engine, schema):
    dtype = {'profileid':VARCHAR(5)} if 'mysql' in engine.dialect.dialect_description else None
    df = _TestsExampleTable.create_example_df(nb_rows=10)
    with AutoDropTableContext(engine=engine, schema=schema, df=df, table_name='test_table_creation',
                              dtype=dtype) as ctx:
        assert not ctx.pse.table_exists()
        ctx.pse.create_table_if_not_exists()
        assert ctx.pse.table_exists()


def test_add_new_columns(engine, schema):
    # store arguments we will use for both AutoDropTableContext and PandasSpecialEngine
    common_kwargs = dict(engine=engine, schema=schema, table_name='test_pandas_special_engine')
    common_kwargs['dtype'] = {'profileid':VARCHAR(5)} if 'mysql' in engine.dialect.dialect_description else None
    df = _TestsExampleTable.create_example_df(nb_rows=10)
    with AutoDropTableContext(df=df, **common_kwargs) as ctx:
        # create our example table
        ctx.pse.create_table_if_not_exists()
        ctx.pse.upsert(if_row_exists='update')
        # try to add new columns (but no JSON ones, it's not supported by sqlalchemy compilers :( )
        df = df.assign(new_text_col='test',
                       new_int_col=0,
                       new_float_col=1.1,
                       new_bool_col=False,
                       new_dt_col=pd.Timestamp('2020-01-01'),
                       # create this col for later
                       empty_col=None)

        # recreate pse (so that a new table model with the new columns is created) then add columns
        # note that we don't need to overwrite `ctx.pse` since the __exit__ method that drops the table will still work
        # (engine, schema and table name did not change)
        pse = PandasSpecialEngine(df=df, **common_kwargs)
        pse.add_new_columns()


@pytest.mark.parametrize("new_empty_column_value", [1, 1.1, "abc", pd.Timestamp("2020-01-01", tz='UTC'), {'foo':'bar'}, ['foo'], True])
def test_change_column_type_if_column_empty(engine, schema, new_empty_column_value):
    df = _TestsExampleTable.create_example_df(nb_rows=10)
    # store arguments we will use for both AutoDropTableContext and PandasSpecialEngine
    common_kwargs = dict(engine=engine, schema=schema, table_name='test_alter_dtype_empty_col')
    common_kwargs['dtype'] = {'profileid':VARCHAR(5)} if 'mysql' in engine.dialect.dialect_description else None
    with AutoDropTableContext(df=df, **common_kwargs) as ctx:
        # create our example table
        ctx.pse.create_table_if_not_exists()
        ctx.pse.upsert(if_row_exists='update')
        # skip for sqlite as it does not support such alteration
        if ctx.pse._db_type == 'sqlite':
            pytest.skip()

        # hack to set any type of element as a column value without pandas trying to broadcast it if it is a list or such 
        df['empty_col'] = df.index.map(lambda x: new_empty_column_value)
        # recreate pse then change column type
        pse = PandasSpecialEngine(df=df, **common_kwargs)
        pse.adapt_dtype_of_empty_db_columns()


# -

# # Test errors

# +
def test_error_index_level_named(engine, schema):
    df = pd.DataFrame({'test':[0]})
    with pytest.raises(IndexError) as excinfo:
        pse = PandasSpecialEngine(engine=engine, schema=schema, table_name='x', df=df)
        assert "All index levels must be named" in str(excinfo.value)

@pytest.mark.parametrize("option", ['index and column collision', 'columns duplicated', 'index duplicated'])
def test_duplicated_names(engine, schema, option):
    df = pd.DataFrame({'test':[0]})
    if option == 'index and column collision':
        df.index.name = 'test'
    elif option == 'columns duplicated':
        df.index.name = 'ix'
        df = df[['test', 'test']]
    elif option == 'index duplicated':
        df = df.set_index(['test', 'test'])
    else:
        raise AssertionError(f'Unexpected value for param `option`: {option}')

    with pytest.raises(ValueError) as excinfo:
        pse = PandasSpecialEngine(engine=engine, schema=schema, table_name='x', df=df)
        assert "There cannot be duplicated names" in str(excinfo.value)


def test_non_unique_index(engine, schema):
    df = pd.DataFrame(index=pd.Index(data=[0, 0], name='ix'))
    with pytest.raises(IndexError) as excinfo:
        pse = PandasSpecialEngine(engine=engine, schema=schema, table_name='x', df=df)
        assert "The index must be unique" in str(excinfo.value)


@pytest.mark.parametrize("bad_chunksize_value", [0, -1, 1.2])
def test_bad_chunksize(engine, schema, bad_chunksize_value):
    df = pd.DataFrame({'test':[0]})
    df.index.name = 'id'
    pse = PandasSpecialEngine(engine=engine, schema=schema, table_name='x', df=df)
    with pytest.raises(ValueError) as excinfo:
        pse._create_chunks(values=[0], chunksize=bad_chunksize_value)
        assert "integer strictly above 0" in str(excinfo.value)
