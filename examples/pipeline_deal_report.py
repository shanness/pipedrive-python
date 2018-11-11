import sys 
sys.path.append('..')
from pipedrive.client import *
client = Client() # setup in pipedrive_settings.json
pipelines = client.get_pipelines()
client.get_stages() # This will link all the stages to the pipelines, and cache them ready to be linked to deals

pname = pipelines[0].name
# get_by_name and get_by_id on all entities
pipeline = Pipeline.get_by_name(pname)[0]
deals = client.get_pipeline_deals(pipeline.id)

person = deals[2].person
print("Person ", person, "from", person.org, "has", len(person.deals), "deals, the first is in pipeline", person.deals[0].pipeline.name, "in stage", person.deals[0].stage.name)

print("That pipeline has the following stages : ",[stage.name for stage in person.deals[0].pipeline.stages])
#print("The custom fields on Deal are : ",Deal.custom_fields.keys())
#print("The custom fields on Person are : ",Person.custom_fields.keys())
#print("Deal fields are",deals[1].get_field_names())

person = None
for pipeline in pipelines:
    if not client.get_pipeline_deals(pipeline.id):
        print("No deals for ",pipeline.name)
        continue
    print(" ----------  Processing ",pipeline," -----------")
    for stage in pipeline.stages:
        deals = stage.deals
        if not deals:
            print("No deals for ",stage)
            continue
        print(" ----------  ",stage," -----------")
        print("{0:<10} {1:<50} {2:<35} {3:<35} {4:<20} {5:<15}".format("Deal ID#","Org","Name","Next Stage","Rotten Time","Status"))
        print("{0:<10} {1:<50} {2:<35} {3:<35} {4:<20} {5:<15}".format("========","==========","==========","==========","==========","=========="))
        for deal in deals:
            # Next and prev stage available from pipeline object
            next_stage = deal.pipeline.get_next_stage(deal.stage)
            next_stage_name = "" if next_stage is None else next_stage.name
            print("{0:<10} {1:<50} {2:<35} {3:<35} {4:<20} {5:<15}".format(deal.id,str(deal.org_name),str(deal.person_name),next_stage_name,str(deal.rotten_time),deal.status))
            person = deal.person

