import graphene
from crm.schema import Query as CRMQuery, Mutation as CRMMutation


# class Query(graphene.ObjectType):
#     hello = graphene.String(default_value="Hello, GraphQL!")

# schema = graphene.Schema(query=Query)


class Query(CRMQuery, graphene.ObjectType):
    # You can add project-level query fields here later
    pass

class Mutation(CRMMutation, graphene.ObjectType):
    # You can add project-level mutation fields here later
    pass

schema = graphene.Schema(query=Query, mutation=Mutation)

