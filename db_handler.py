from sqlalchemy import create_engine, MetaData

class DatabaseHandler:
    def __init__(self,db_url):
        self.engine = create_engine(db_url)
        self.metadata = MetaData(self.engine)
        self.metadata.reflect(bind=self.engine)

    def get_metadata(self):
        return self.metadata

    def execute_query(self,query):
        with self.engine.connect() as connection:
            result = connection.execute(query)
            return [dict(row) for row in result]