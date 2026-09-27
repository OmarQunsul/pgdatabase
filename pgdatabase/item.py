from psycopg.rows import dict_row
from datetime import datetime, timedelta
import json

#TODO: Write some documentation
#TODO: Extract the PostgreSQL functionality into an adapter. And add SQLite adapter as well

#note = Note.find(67)
#print(note.title)
#Note.create({"title": "NEW", "text": "FGDSDFG", "user_id": 9})

# TODO: Not complete yet
class Relation:
    def __new__(cls, *args, **kwargs):
        # Overriding the constructor here
        # This is called before the __init__
        # Can be used when you need to control the object creation process, like in the case of
        # singletons or when you want to inherit from immutable classes.
        # Not a very helpful article though:
        # https://builtin.com/data-science/new-python
        instance = super().__new__(cls)
        return instance

    def __init__(self, cls):
        self.cls = cls
        self.items = None
        self.limit_number = None
        self.offset_number = None
        self.conditions = {}
        self.pointer = None
        self.order_by = "id DESC"
        self.custom_condition_strings = [] # RAW LEVEL. Used for searching array elements for now

    def __len__(self):
        if self.items is None: self.reload()
        return len(self.items)

    def first(self, count = None):
        if self.items is None:
            self.limit_number = 1 if count == None else count
            self.reload()
        if count == None:
            return self.items[0] if len(self.items) > 0 else None
        else:
            return self.items[:count]

    def last(self):
        if self.items is None: self.reload()
        return self.items[-1] if len(self.items) > 0 else None

    def where(self, conditions: dict):
        self.conditions = {**self.conditions, **conditions}
        return self

    def order(self, order_by):
        self.order_by = order_by
        return self

    def limit(self, number):
        self.limit_number = number
        return self

    def offset(self, number):
        self.offset_number = number
        return self

    # Size of the records
    def size(self):
        if self.items is None:
            self.reload()
        return len(self.items)

    def to_sql(self):
        # TODO: Figure out a way to return the sql command from cur
        return ""

    def delete(self):
        cls = self.cls
        cur = cls.conn().cursor(row_factory = dict_row)
        condition_strings = []
        for key in self.conditions:
            #val = self.conditions[key]
            condition_strings.append(f"{key} = %s")
        command = f"DELETE FROM {cls.table_name} {'WHERE' if len(condition_strings) > 0 else ''} {' AND '.join(condition_strings)}"
        result = cur.execute(command, tuple(self.conditions.values()))
        cls.conn().commit()
        print(result)
        return result

    def count(self):
        cls = self.cls
        cur = cls.conn().cursor(row_factory = dict_row)
        condition_strings = []
        arguments = []
        if self.conditions:
            for key in self.conditions:
                val = self.conditions[key]
                if val == None:
                    condition_strings.append(f"{key} IS NULL")
                elif type(val) is list or type(val) is tuple:
                    condition_strings.append(f"{key} = ANY(%s)")
                    arguments.append(list(val))
                else:
                    condition_strings.append(f"{key} = %s")
                    arguments.append(val)
        command = f"SELECT count(*) FROM {cls.table_name} {'WHERE' if len(condition_strings) > 0 else ''} {' AND '.join(condition_strings)}"
        cur.execute(command, tuple(self.conditions.values()))
        cls.conn().commit()
        for record in cur:
            return record["count"]

    def max(self, attribute):
        cls = self.cls
        cur = cls.conn().cursor(row_factory = dict_row)
        condition_strings = []
        for key in self.conditions:
            #val = self.conditions[key]
            condition_strings.append(f"{key} = %s")
        # SQL Injection threat?
        command = f"SELECT max({attribute}) FROM {cls.table_name} {'WHERE' if len(condition_strings) > 0 else ''} {' AND '.join(condition_strings)}"
        cur.execute(command, tuple(self.conditions.values()))
        cls.conn().commit()
        for record in cur:
            return record["max"]

    def reload(self):
        cls = self.cls
        query = f"SELECT * FROM {cls.table_name}"
        condition_strings = []
        arguments = []
        self.items = []
        if self.conditions:
            for key in self.conditions:
                val = self.conditions[key]
                if val == None:
                    condition_strings.append(f"{key} IS NULL")
                elif type(val) is list or type(val) is tuple:
                    condition_strings.append(f"{key} = ANY(%s)")
                    arguments.append(list(val))
                else:
                    condition_strings.append(f"{key} = %s")
                    arguments.append(val)
        if self.custom_condition_strings:
            for arr in self.custom_condition_strings:
                condition_strings.append(arr[0])
                for it in arr[1:]:
                    arguments.append(it)
        if condition_strings:
            query += f" WHERE {' AND '.join(condition_strings)}"
        if self.order_by:
            query += f" ORDER BY {self.order_by}"
        if self.limit_number:
            query += f" LIMIT {self.limit_number}"
        if self.offset_number:
            query += f" OFFSET {self.offset_number}"
        cur = cls.conn().cursor(row_factory = dict_row)
        cur.execute(query, tuple(arguments))
        cls.conn().commit()
        for record in cur:
            obj = cls()
            for k in record:
                obj.item_original_attributes[k] = record[k]
                setattr(obj, k, record[k])
            self.items.append(obj)
        return

    def __iter__(self):
        self.pointer = 0
        return self

    def __next__(self):
        if self.items is None: self.reload()
        if self.pointer == len(self.items): raise StopIteration

        item = self.items[self.pointer]
        self.pointer += 1
        return item

class Item:
    updated_at = True # TODO: Make it smart on whether there is an updated_at column in the table
    connection = None

    def __init__(self, attributes = None) -> None:
        self.item_original_attributes = {}
        if attributes is not None:
            self.assign_attributes(attributes)
        self.assign_attributes({"id": None})

    @classmethod
    def find(cls, id):
        obj = cls()
        cur = cls.conn().cursor(row_factory = dict_row)
        cur.execute(f"SELECT * from {cls.table_name} WHERE id = %s LIMIT 1", (id,))
        cls.conn().commit()
        for record in cur:
            for k in record:
                setattr(obj, k, record[k])
                obj.item_original_attributes[k] = record[k]
            return obj
        return None

    def delete(self):
        cur = self.conn().cursor(row_factory = dict_row)
        cur.execute(f"DELETE from {self.table_name} WHERE id = %s", (self.id,))
        self.conn().commit()
        return None

    def changed(self):
        ret = {}
        for k in self.item_original_attributes:
            if getattr(self, k) != self.item_original_attributes[k]:
                ret[k] = [self.item_original_attributes[k], getattr(self, k)]
        return ret

    # Called after the save
    def sync_changes(self):
        ret = {}
        for k in self.item_original_attributes:
            if getattr(self, k) != self.item_original_attributes[k]:
                self.item_original_attributes[k] = getattr(self, k)
        return ret

    def update(self, attributes):
        self.assign_attributes(attributes)
        self.save()
        return None

    def assign_attributes(self, attributes): # doesn't save
        for k in attributes:
            setattr(self, k, attributes[k])
        if k not in self.item_original_attributes:
            self.item_original_attributes[k] = None

    def persisted(self) -> bool: # TODO: Should check the database. Write tests
        return self.id != None

    def save(self):
        # Can you improve this code
        if self.persisted():
            cur = self.conn().cursor(row_factory = dict_row)
            l = []
            updates = []
            # Generating the list of the attributes. Should use the changed()
            changed_attributes = self.changed()
            if len(changed_attributes) == 0:
                return
            for k in changed_attributes:
                updates.append(f"{k} = %s")
                l.append(changed_attributes[k][-1])
            l.append(self.id)
            cur.execute(f"UPDATE {self.table_name} SET {','.join(updates)} WHERE id = %s", l)
            # commit the transaction
            self.conn().commit()
            # clear the changed attributes
        else:
            cls = type(self)
            attrs = {}
            changed_attributes = self.changed()
            for k in changed_attributes:
                attrs[k] = getattr(self, k)
            obj = cls.create(attrs)
            self.assign_attributes({"id": obj.id})

        self.sync_changes()

    @classmethod
    def relation(cls) -> Relation: # For now conditions are equal operators, and only 1 value for now
        return Relation(cls)

    @classmethod
    def limit(cls, number) -> Relation: # For now conditions are equal operators, and only 1 value for now
        rel = cls.relation()
        rel.limit(number)
        return rel

    @classmethod
    def first(cls, count = None) -> Relation: # For now conditions are equal operators, and only 1 value for now
        rel = cls.relation()
        return rel.first(count)

    @classmethod
    def to_sql(cls) -> str: # For now conditions are equal operators, and only 1 value for now
        return cls.relation().to_sql()

    @classmethod
    def count(cls) -> str: # For now conditions are equal operators, and only 1 value for now
        return cls.relation().count()

    @classmethod
    def where(cls, conditions: dict) -> Relation:
        rel = cls.relation()
        rel.where(conditions)
        return rel

    @classmethod
    def all(cls) -> Relation:
        rel = cls.relation()
        return rel

    @classmethod
    def order(cls, order_by: str) -> Relation:
        rel = cls.relation()
        rel.order(order_by)
        return rel

    # This is to support JSON fields
    @classmethod
    def decode(cls, val) -> str:
        if type(val) == dict or type(val) == list:
            return json.dumps(val)
        else:
            return val

    @classmethod
    def create(cls, attributes):
        keys = attributes.keys()
        if "created_at" not in attributes:
            attributes["created_at"] = datetime.now()
        if "updated_at" not in attributes and cls.updated_at:
            attributes["updated_at"] = datetime.now()
        cur = cls.conn().cursor(row_factory = dict_row)
        print([cls.decode(attributes[key]) for key in keys])
        cur.execute(
                f"INSERT INTO {cls.table_name}({','.join(keys)}) VALUES ({','.join(['%s'] * len(keys))}) RETURNING {','.join(['id'] + list(keys))}",
                tuple([cls.decode(attributes[key]) for key in keys])
                )
        cls.conn().commit()

        for record in cur:
            id = record["id"]

        return cls.find(id)

    @classmethod
    def create_or_update(cls, attributes, conflict_target = None):
        updates = []
        l = []
        for k in attributes:
            updates.append(f"{k} = %s")
            l.append(attributes[k])
        if conflict_target:
            conflict_statement = f"ON CONFLICT ({conflict_target}) DO UPDATE SET {', '.join(updates)}"
        else:
            conflict_statement = f"ON CONFLICT DO UPDATE SET {', '.join(updates)}"

        keys = attributes.keys()
        if "created_at" not in attributes:
            attributes["created_at"] = datetime.now()
        if "updated_at" not in attributes and cls.updated_at:
            attributes["updated_at"] = datetime.now()
        cur = cls.conn().cursor(row_factory = dict_row)
        cur.execute(
                f"INSERT INTO {cls.table_name}({','.join(keys)}) VALUES ({','.join(['%s'] * len(keys))}) {conflict_statement} RETURNING {','.join(['id'] + list(keys))}",
                tuple([cls.decode(attributes[key]) for key in keys] + l)
                )
        cls.conn().commit()

        for record in cur:
            id = record["id"]

        return cls.find(id)
