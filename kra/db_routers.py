from kra import models


# See https://docs.djangoproject.com/en/3.0/topics/db/multi-db/#an-example
class PSRouter:
    def db_for_read(self, model, **hints):
        if model == models.PSRecord:
            return 'ps'
        return None

    def db_for_write(self, model, **hints):
        if model == models.PSRecord:
            return 'ps'
        return None

    def allow_relation(self, obj1, obj2, **hints):
        if obj1.__class__ == models.PSRecord or obj2.__class__ == models.PSRecord:
            return True
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label == 'kra' and model_name == 'psrecord':
            return db == 'ps'
        return None
