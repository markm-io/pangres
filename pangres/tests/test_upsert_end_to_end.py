#!/usr/bin/env python
# coding: utf-8
"""
End to end test similar to the scenario proposed in the docstring
of `pangres.upsert`.

We will create a table and then insert with update and then ignore for the
`ON CONFLICT` clause.
"""
import pandas as pd
import pytest
from sqlalchemy import VARCHAR
from pangres import upsert
from pangres.examples import _TestsExampleTable
from pangres.exceptions import HasNoSchemaSystemException
from pangres.tests.conftest import read_example_table_from_db, AutoDropTableContext


# # Helpers

utc_ts = lambda s: pd.Timestamp(s, tz='UTC')

# # Config

table_name = 'test_upsert_end_to_end'


# # Test data

# +
# df from which we will create a SQL table
df = _TestsExampleTable.create_example_df(nb_rows=6)
# test nulls won't create any problems
# avoid nulls in boolean column though as this is unpractical with pandas in older versions
df.iloc[0,[ix for ix, col in enumerate(df.columns) if col != 'likes_pizza']] = None

# df from which we will upsert update or upsert ignore
# remove one record from above and add one
# so we know that 1) old records are still there, 2) new ones get added
# 3) we can check whether the update/ignore of existing records worked
df2 = _TestsExampleTable.create_example_df(nb_rows=7)
df2 = df2.iloc[1:]
# -

# # Expectations

# +
df_after_insert_update = pd.concat(objs=(df.loc[~df.index.isin(df2.index.tolist())], # everything that is not in df2
                                         df2))

df_after_insert_ignore = pd.concat(objs=(df,
                                         df2.loc[~df2.index.isin(df.index.tolist())])) # everything that is not in df


# -

# # Tests

# +
# after the table is created with a first `upsert`
# using `create_table=False` or `create_table=True` should both work
@pytest.mark.parametrize('create_table', [False, True], ids=['create_table_false', 'create_table_true'])
@pytest.mark.parametrize('if_row_exists, df_expected', [['update', df_after_insert_update],
                                                        ['ignore', df_after_insert_ignore]],
                         ids=['update', 'ignore'])
def test_end_to_end(engine, schema, create_table, if_row_exists, df_expected):
    # helpers
    ## dtype for index for MySQL... (can't have flexible text length)
    dtype = {'profileid':VARCHAR(10)} if 'mysql' in engine.dialect.dialect_description else None
    read_table = lambda: read_example_table_from_db(engine=engine, schema=schema, table_name=table_name).sort_index()

    with AutoDropTableContext(engine=engine, schema=schema, table_name=table_name):
        # 1. create table
        upsert(engine=engine, schema=schema, df=df, if_row_exists=if_row_exists, dtype=dtype, table_name=table_name,
               create_table=True)
        pd.testing.assert_frame_equal(df, read_table())

        # 2. insert update/ignore
        upsert(engine=engine, schema=schema, df=df2, if_row_exists=if_row_exists, dtype=dtype, table_name=table_name,
               create_table=create_table)
        pd.testing.assert_frame_equal(df_expected, read_table())


def test_create_schema_none(engine, schema):
    """
    If `create_schema` is True in `pangres.upsert` but the schema is `None`
    we should not raise an error even if it is a database that does not
    support schemas
    """
    df = pd.DataFrame({'id':[0]}).set_index('id')
    with AutoDropTableContext(engine=engine, schema=None, table_name='test_create_schema_none') as ctx:
        upsert(engine=engine, schema=ctx.schema, df=df, if_row_exists='update', create_schema=True,
               table_name=ctx.table_name, create_table=True)


def test_create_schema_not_none(engine, schema):
    df = pd.DataFrame({'id':[0]}).set_index('id')
    with AutoDropTableContext(engine=engine, df=df, schema=None, table_name='test_create_schema_none') as ctx:
        try:
            upsert(engine=engine, schema=ctx.schema, df=df, if_row_exists='update', create_schema=True,
                   table_name=ctx.table_name, create_table=True)
        except Exception as e:
            # for postgres this should have worked
            if ctx.pse._db_type == 'postgres':
                raise e
            else:
                assert isinstance(e, HasNoSchemaSystemException)
