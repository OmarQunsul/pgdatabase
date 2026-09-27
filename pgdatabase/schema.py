from .migrate import Table, Column, Index
import yaml

def _read_config(filename):
    with open(filename, 'r') as file:
        content = yaml.safe_load(file)
        return content

def _setup_database(conn, config):
    for table_name, table_info in config['tables'].items():
        with Table(conn, table_name) as table:
            for column in table_info['columns']:
                table.columns.append(Column(column['name'], column['type'], primary_key=column.get('primary_key', False), default=column.get('default', False), not_null=column.get('not_null', False), array=column.get('array', False)))
            # If indexes need to be processed
            indexes = table_info.get('indexes', [])
            for index in indexes:
                table.indexes.append(Index(index['name'], index['columns'], type=index['type'], unique=index.get('unique', False)))
            table.migrate()
        print(f"Migrated {table_name} Table")

# Public
def schema_migrate(conn, file):
    config = _read_config(file)
    _setup_database(conn, config)