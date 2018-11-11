import sys 
sys.path.append('..')
from pipedrive.client import *
from collections import Counter
client = Client() # setup in pipedrive_settings.json

# Load up to 5000 people, with automatic pagination
persons = client.get_persons(limit=5000)

person=persons[0]

# All field names exposed as attributes and queryable
# All data (as per original API) is still available as person.data
print("Person field names :",person.org.get_field_names())

# Navigation between objects possible. org currently a stub
# nice to string on entities
print(person,"has",person.org)

# Report on how many people are connected to an org
count = Counter([p.org is not None for p in persons])
print("persons with org ",count)

# Report which orgs are stubs (before we load up the orgs)
count = Counter([p.org.stub for p in persons if p.org])
print("Person Orgs that are stubs ",count)

# Shows which fields are available on these stubs
print("Org field names (from person stubs): ",person.org.get_field_names())

print("LOADING ORGS")
# Load all the orgs, refreshing the stubs created above
orgs = client.get_organizations(limit=5000)

# Report stub status now
count = Counter([p.org.stub for p in persons if p.org])
print("Person Orgs that are stubs ",count)

# Show field names for 
print("Org field names : ",person.org.get_field_names())

# Show that all loaded orgs are not stubs (even though some persons might have some if org was deleted)
count = Counter([org.stub for org in orgs])
print("Orgs that are stubs ",count)

# Modify entities
person.name = "New Name"
# Including custom fields
# person.admin = 'Yes' # This is validated as valid value.

# List modified fields
print(person," has these fields modified",person.modified_fields)

# Save changes (not doing to avoid stuffing your data)
# client.save_changes(person)
# This saves, refreshes the cache, and clears modified fields

# revert changes
client.get_persons(person_id=person.id) # Note, no need to catch this, person is now updated
print(person,"has these fields modified after reload",person.modified_fields)

# Report on the first 5 using convenience methods (org_name and email_address), can also include custom fields like person.admin)
print("{0:<10} {1:<40} {2:<45} {3:<45}".format("Person ID#","Org","Name","Email"))
print("{0:<10} {1:<40} {2:<45} {3:<45}".format("=========","==========","==========","=========="))
for person in persons[0:5]:
    print("{0:<10} {1:<40.40} {2:<45.45} {3:<45}".format(person.id,person.org_name,person.name,person.email_address))
#    print("{0:<10} {1:<40.40} {2:<45.45} {3:<45}".format(str(person.id),str(org_name),str(person.name),str(person.email_address),str(person.admin),str(person.has_app_installed)))


