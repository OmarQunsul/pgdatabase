import os
import psycopg
from psycopg.rows import dict_row

# Migration Tool
## Python tool to automatically create/modify the tables and their schema.

class Column:
    def __init__(self, name, column_type, primary_key = False, array = False, not_null = False, default = None, old_name = None):
        self.name = name
        self.column_type = column_type
        self.primary_key = primary_key
        self.not_null = True if primary_key else not_null
        self.default = str(default) if default else None
        self.array = array
        self.old_name = old_name

    def rendered_column_type(self):
        if self.array:
            return self.column_type + "[]"
        else:
            return self.column_type

    def __str__(self):
        """The string representation of the column"""
        if self.primary_key:
            return "%s serial PRIMARY KEY" % (self.name, )
        else:
            s = "%s %s" % (self.name, self.column_type)
            if self.array:
                s += " ARRAY"
            if self.not_null:
                s += " NOT NULL"
            if self.default != None:
                s += " DEFAULT " + self.default
            return s

class Index:
    def __init__(self, name, columns, type = "btree", unique = False, old_name = None, concurrent = False):
        self.name = name
        self.columns = columns
        self.type = type
        self.unique = unique
        self.concurrent = concurrent
        self.old_name = old_name # For renaming

    def creating_sql(self, table_name):
        # Reference: https://www.postgresql.org/docs/14/sql-createindex.html
        sql = "CREATE "
        if self.unique:
            sql += "UNIQUE INDEX "
        else:
            sql += "INDEX "
        if self.concurrent:
            sql += "CONCURRENTLY "
        sql += "IF NOT EXISTS " + self.name + " ON " + table_name + " "
        sql += "USING " + self.type + " "
        if type(self.columns) == str:
            sql += "(" + self.columns + ")"
        elif type(self.columns) == list or type(self.columns) == tuple:
            sql += "(" + ",".join(self.columns) + ")"
        return sql

class Table:
    def __init__(self, conn, name):
        self.conn = conn
        self.conn2 = psycopg.connect(self.conn.info.dsn + " password=" + self.conn.info.password, autocommit=True)
        self.name = name
        self.columns = []
        self.indexes = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def exists(self):
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(f"SELECT * FROM pg_catalog.pg_tables WHERE schemaname = 'public' AND tablename = %s LIMIT 1", (self.name,))
            for record in cur:
                return True
        self.conn.commit()
        return False

    def existing_columns(self):
        # This is needed for Array columns

        # TODO: Convert the database column spec into a Column() Object, to make it easy to compare the diff between two columns
        db_columns = {}
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(f"""SELECT column_name AS name, c.data_type AS column_type, is_nullable, e.data_type as element_types,
            c.character_maximum_length as char_limit,
            e.character_maximum_length as array_char_limit,
            column_default AS default
            FROM information_schema.columns as c
            LEFT JOIN information_schema.element_types e
            ON ((c.table_catalog, c.table_schema, c.table_name, 'TABLE', c.dtd_identifier)
            = (e.object_catalog, e.object_schema, e.object_name, e.object_type, e.collection_type_identifier))
            WHERE table_schema = 'public' AND table_name = %s""", (self.name,))
            for record in cur:
                record["not_null"] = (record["is_nullable"] == "NO")
                db_columns[record["name"]] = record
                if record["column_type"] == "ARRAY":
                    if record["array_char_limit"]:
                        record["column_type"] = "OMAR" # TODO Fix !
                    else:
                        record["column_type"] = record["element_types"] + "[]"
                if record["char_limit"] != None:
                    record["column_type"] += "(" + str(record["char_limit"]) + ")"
        self.conn.commit()
        return db_columns

    def existing_indexes(self):
        db_indexes = {}
        # TODO: Convert the database index spec into a Index() Object, to make it easy to compare the diff between two columns
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(f"""SELECT indexname AS name, indexdef AS def
                    FROM pg_indexes WHERE tablename = %s""", (self.name,))
            # indexdef looks like this : 'CREATE UNIQUE INDEX notes_pkey ON public.notes USING btree (id)'
            for record in cur:
                db_indexes[record["name"]] = record
        self.conn.commit()
        return db_indexes

    def exec_command(self, command):
        print(command)
        if command.startswith("CREATE INDEX CONCURRENTLY"):
            self.conn2.execute(command)
        else:
            self.conn.execute(command)
            self.conn.commit()

    def create(self, dry_run = False) -> str:
        command = "CREATE TABLE IF NOT EXISTS %s(" % (self.name,)
        command += ", ".join(map(lambda column: str(column), self.columns))
        command += ")"
        if not dry_run:
            self.exec_command(command)
        return command

    def drop(self):
        command = "DROP TABLE IF EXISTS %s" % (self.name,)
        self.exec_command(command)

    def truncate(self):
        command = "TRUNCATE TABLE %s" % (self.name,)
        self.exec_command(command)

    def migrate(self, dry_run = False):
        commands = []
        just_created = False
        if not self.exists():
            just_created = True
            commands.append(self.create(dry_run=dry_run))

        if not just_created:
            # Columns in the Definitions
            columns_mapping = {}
            for column in self.columns:
                columns_mapping[column.name] = column

            # Columns in the Database
            db_columns = self.existing_columns()

            alter_command_parts = []

            renamed_columns = dict()
            # Renaming columns
            for column in self.columns:
                if column.old_name and column.old_name in db_columns:
                    renamed_columns[column.old_name] = column
                    commands.append("ALTER TABLE %s RENAME COLUMN %s TO %s" % (self.name, column.old_name, column.name))

            # Creating new columns
            for column in self.columns:
                if column.name not in db_columns and column.old_name is None:
                    alter_command_parts.append("ADD COLUMN %s" % (column))

            # Dropping old columns
            remove_columns = set(db_columns) - set([column.name for column in self.columns]) - set(renamed_columns)
            for column in remove_columns:
                alter_command_parts.append("DROP COLUMN IF EXISTS %s" % (column))

            # Modifying Columns
            for column in columns_mapping:
                col1 = columns_mapping[column] # New column spec. Column Object
                col2 = None
                if column in db_columns:
                    col2 = db_columns[column] # Existing column spec. Dictionary
                if col1.old_name is not None:
                    if col1.old_name in db_columns:
                        col2 = db_columns[col1.old_name]
                    # TODO: Introduce Strict Mode that checks for the existing of old columns
                    #else:
                    #    raise Exception(f"Column {col1.old_name} does not exist")

                if col2 is not None:
                    # Modifying Column Type
                    # We skip ARRAY columns for now because it's hard to get the character limit on internal elements
                    if not col1.array:
                        if not col1.primary_key and (col1.rendered_column_type() != col2["column_type"]):
                            #print("Changing data type of column " + col1.name)
                            #print(col1.rendered_column_type())
                            #print(col2["column_type"])
                            alter_command_parts.append("ALTER COLUMN %s TYPE %s" % (column, col1.rendered_column_type()))

                    # Modifying Default Value
                    if not col1.primary_key and col1.default != col2["default"]: # Primary Keys have a default value from the sequence
                        if col1.default is None:
                            alter_command_parts.append("ALTER COLUMN %s DROP DEFAULT" % column)
                        else:
                            alter_command_parts.append("ALTER COLUMN %s SET DEFAULT %s" % (column, col1.default))

                    # Modifying NOT NULL
                    if col1.not_null != col2["not_null"]:
                        if col1.not_null:
                            alter_command_parts.append("ALTER COLUMN %s SET NOT NULL" % column)
                        else:
                            alter_command_parts.append("ALTER COLUMN %s DROP NOT NULL" % column)

            if len(alter_command_parts) > 0:
                alter_command = "ALTER TABLE IF EXISTS %s " % self.name
                alter_command += ", ".join(alter_command_parts)
                commands.append(alter_command)

        # Indexes in the Database
        # Extracting information from them
        db_indexes = self.existing_indexes()
        for index in db_indexes:
            record = db_indexes[index]
            record["unique"] = "UNIQUE" in record["def"].split(" ") # Not the best way, but it's fine for now

        # Indexes in the Definitions
        indexes_mapping = {}
        for index in self.indexes:
            indexes_mapping[index.name] = index

        # Creating new indexes
        for index in self.indexes:
            if index.name not in db_indexes and index.old_name is None:
                commands.append(index.creating_sql(self.name))

        # This re-adds the index to the db_indexes with the new name
        for index in self.indexes:
            if index.name not in db_indexes and index.old_name is not None and index.old_name in db_indexes:
                commands.append("ALTER INDEX IF EXISTS %s RENAME TO %s" % (index.old_name, index.name))
                db_indexes[index.name] = db_indexes[index.old_name]
                del db_indexes[index.old_name]

        # Changing Indexes
        for index in self.indexes:
            if index.name in db_indexes:
                if index.unique != db_indexes[index.name]["unique"]:
                    commands.append("DROP INDEX IF EXISTS %s" % (index.name))
                    commands.append(index.creating_sql(self.name))

        # Dropping Indexes
        remove_indexes = set(db_indexes) - set([index.name for index in self.indexes])
        for index_name in remove_indexes:
            if index_name == f'{self.name}_pkey': # Skipping Primary Keys Indexes for now
                continue
            commands.append("DROP INDEX IF EXISTS %s" % (index_name))

        # Modifying indexes won't be able to add or remove columns
        for command in commands:
            if dry_run:
                print(command)
            else:
                self.exec_command(command)

        return commands
