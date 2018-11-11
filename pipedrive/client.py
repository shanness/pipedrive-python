import requests
from urllib.parse import urlencode, urlparse, quote_plus
from base64 import b64encode
import re
import logging

import json

logging.basicConfig(level=logging.WARNING) # Update this to DEBUG see all the cache action
log = logging.getLogger(__name__)

class Entity(object):

    initialised = False # Used to know if the custom fields have been loaded yet
    custom_fields = {} # Set per concrete sub-class of EntityWithCustomFields

    @classmethod
    def getCache(cls):
        raise NotImplemented

    @classmethod
    def refresh_or_construct(cls,data):
        """
        Only to be used by direct API objects returned (i.e. get_persons should call with Person,data
        related entities should use get_or_construct for passing in their stubs.
        :rtype: Type[entity]
        """
        theId = data["id"]
        if cls.id_exists(theId):
            entity = cls.get_by_id(theId)
            old = str(entity)
            entity.data = data
            entity.stub = False
            entity.modified_fields = [] # Clear this.
            log.debug("Refreshing %s with %s in cache %s", old, entity, id(cls.getCache()))
            return entity
        else:
            return cls(data,is_stub=False)

    @classmethod
    def get_or_construct(cls,data,is_stub=True):
        """
        To be used by associated objects in returned API data.
        Note it seems all of these except User are stubs without full data, and some, like deal only have id + name
        :param data:
        :param is_stub:
        :return:
        """
        if "id" not in data and "value" in data:
            theId = data["value"]
        else:
            theId = data["id"]
        if cls.id_exists(theId):
            entity = cls.get_by_id(theId)
            log.debug("Getting cached version of %s from cache %s", entity, id(cls.getCache()))
            return entity
        return cls(data,is_stub)

    def __init__(self, data,is_stub):
        if not Entity.initialised:
            raise Exception("Custom fields not yet initialised, should be impossible")

        if "id" not in data and "value" in data:
            # This means it came from another Entities construction , so copy the data to to avoid changing the original
            self.data = data.copy()
            self.data["id"] = self.data.pop("value")
            self.stub = is_stub
        else:
            self.data = data
            self.stub = is_stub
        log.debug("Creating %s stub=%s in cache %s", self,self.stub, id(self.__class__.getCache()))
        if not self.__class__.getCache():
            log.debug("%s first object added to cache, data is : %s",self,data)
        self.modified_fields = []
        self.__class__.getCache()[self.data["id"]] = self

    @classmethod
    def get_by_id(cls, id):
        return cls.getCache().get(id,None)

    @classmethod
    def id_exists(cls, id):
        return id in cls.getCache()

    @classmethod
    def get_by_name(cls, name):
        return [e for e in cls.getCache().values() if e.name == name]

    def __getattr__(self, name):
        if (name in self.custom_fields):
            return self.__get_custom_field(name)
        value = self.data.get(name,"Invalid field name" + name)
        return value

    def __setattr__(self, name, value):
        if name == "data": # Note, this must be set before any other field (in this super class) to avoid infinite recursion
            object.__setattr__(self,name,value)
        selfdata = self.__dict__["data"]
        if name in self.custom_fields:
            custom_field = self.custom_fields[name]
            key = custom_field["key"]
            val_to_set = value
            if ("fields" in custom_field):
                val_to_set = [ k for k,v in custom_field["fields"].items() if v == value]
                if not val_to_set:
                    raise Exception("Value '" + value + "' is not a valid value for field, valid values are " + str(list(custom_field["fields"].values())))
                val_to_set = val_to_set[0] # There should only be one, and need to de-list
            log.info("Modified custom field %s(%s) from %s(%s) to %s(%s)",name,key,self.__get_custom_field(name),selfdata[key],value,val_to_set)
            selfdata[key] = val_to_set
            self.modified_fields.append(key)
            return
        if name in selfdata:
            log.info("Modified field '%s' from '%s' to '%s')",name,selfdata[name],value)
            selfdata[name] = value
            self.modified_fields.append(name)
            return
        object.__setattr__(self,name,value)


    def get_field_names(self):
        """
        Get all field names for this entity, using custom field names instead of the pipedrive key
        :return:
        """
        return [self.get_custom_field_name(key) for key in self.data.keys()]

    def __get_custom_field(self,name):
        key = self.custom_fields[name]["key"]
        if key in self.data:
            value = self.data[key]
            if value is None:
                return value
            if ("fields" in self.custom_fields[name]):
                return self.custom_fields[name]["fields"].get(value,"Invalid field value " + value)
        log.warning("{},{} Not found for {}[{}]".format(name, key, self.__class__.__name__, self))
        log.warning("%s",self.data)
        return ("{} Not found".format(name))

    def repr(self):
        return "(" + str(self.id)  + "," + str(self.name) + ")"

    def __str__(self):
        return self.__class__.__name__  + self.repr()

    def get_custom_field_name(self,key):
        """
        Get the custom fieldname for a pipedrive's key
        :param key:
        :return: the passed in name if not found (assumes it's not custom)
        """
        names = [ k for k,v in self.custom_fields.items() if v["key"]==key ]
        if not names:
            return key # assumes it's not custom
        if len(names) > 1:
            raise NameError("There are " + str(len(names)) + " matches found in custom_fields for key " + key)
        return names[0]

    def __repr__(self):
        if self.data:
            repr = [{self.get_custom_field_name(key):self.data[key]} for key in self.data.keys()]
            return str(repr)
        return "No data"
#        return str(self.data)


class EntityWithCustomFields(Entity):
    pass


# Just for shared convenience properties
class EntityWithOrganisations():

    @property
    def org_name(self):
        if self.org:
            return self.org.name
        else:
            return ""


# Just for shared convenience properties
class EntityWithEmail():

    @property
    def email_address(self):
        if "email" in self.data:
            return str(self.data["email"][0]["value"])
        return ""


class Person(EntityWithCustomFields,EntityWithOrganisations,EntityWithEmail):

    _by_id = {}

    @classmethod
    def getCache(cls):
        return cls._by_id

    def __init__(self, data, is_stub):
        super().__init__(data,is_stub)
        self.deals = []
        self.notes = []
        if "org_id" in data and data["org_id"]: # Can have None in data
            self.org = Organization.get_or_construct(data["org_id"])
        else:
            self.org = None
        if "owner_id" in data and data["owner_id"]:
            self.owner = User.get_or_construct(data["owner_id"],is_stub=False)
        else:
            self.owner = None


class Organization(EntityWithCustomFields):
    _by_id = {}

    @classmethod
    def getCache(cls):
        return cls._by_id

    def __init__(self, data, is_stub):
        super().__init__(data,is_stub)
        self.deals = []
        self.notes = []

class Deal(EntityWithCustomFields,EntityWithOrganisations):
    _by_id = {}

    @classmethod
    def getCache(cls):
        return cls._by_id

    def __init__(self, data, is_stub):
        super().__init__(data,is_stub)
        self.notes = []
        # Have to test all of this, because for notes, the note data might be the old objects, so it's not passed in
        if "pipeline_id" in data:
            self.pipeline = Pipeline.get_or_construct({"id":data["pipeline_id"],"name":"Unknown (from deal)"})
            self.pipeline.deals.append(self)
        if "stage_id" in data:
            self.stage = Stage.get_or_construct({"id":data["stage_id"],"name":"Unknown (from deal)","pipeline_id":data["pipeline_id"]})
            self.stage.deals.append(self)
        # Damn, /deals and /pipeline/#/deals returns different fields.  Latter is an ID, former is an org object.. (for org, user, creator and person)
        if "org_id" in data:
            if type(data["org_id"]) is dict:
                self.org = Organization.get_or_construct(data["org_id"])
            else:
                self.org = Organization.get_or_construct({"id":data["org_id"],"name":data["org_name"]})
            self.org.deals.append(self)
        if "user_id" in data:
            if type(data["user_id"]) is dict:
                self.owner = User.get_or_construct(data["user_id"],is_stub=True)
            else:
                self.owner = User.get_or_construct({"id":data["user_id"],"name":data["owner_name"]},is_stub=True)
        if "creator_user_id" in data:
            if type(data["creator_user_id"]) is dict:
                self.creator = User.get_or_construct(data["creator_user_id"],is_stub=False)
            else:
                self.creator = User.get_or_construct({"id":data["creator_user_id"],"name":"Unknown (from deal)"},is_stub=True)
        if "person_id" in data:
            if type(data["person_id"]) is dict:
                self.person = Person.get_or_construct(data["person_id"],is_stub=True)
            else:
                self.person = Person.get_or_construct({"id":data["person_id"],"name":data["person_name"],"org_id":self.org.data},is_stub=True)
            self.person.deals.append(self)

    @property
    def person_name(self):
        if self.person:
            return self.person.name
        else:
            return ""

class Pipeline(Entity):
    _by_id = {}

    @classmethod
    def getCache(cls):
        return cls._by_id

    def __init__(self, data, is_stub):
        super().__init__(data,is_stub)
        self.stages = [] # Left here to be hooked up if stages are loaded
        self.deals = [] # Left here to be hooked up if deals are loaded

    def get_next_stage(self,stage):
        pos = self.stages.index(stage)
        try:
            return self.stages[pos+1]
        except ValueError:
            return None

    def get_prev_stage(self,stage):
        pos = self.stages.index(stage)
        try:
            return self.stages[pos-1]
        except ValueError:
            return None


class Stage(Entity):
    _by_id = {}

    @classmethod
    def getCache(cls):
        return cls._by_id

    def __init__(self, data, is_stub):
        super().__init__(data,is_stub)
        self.pipeline = Pipeline.get_or_construct({"id":data["pipeline_id"],"name":data.get("pipeline_name","Unknown (from Stage, stub=" + str(is_stub) + ")")})
        self.pipeline.stages.append(self)
        self.deals = []

class User(Entity,EntityWithEmail):
    _by_id = {}

    @classmethod
    def getCache(cls):
        return cls._by_id

    pass

class Product(Entity):
    _by_id = {}

    @classmethod
    def getCache(cls):
        return cls._by_id

    pass

class Note(Entity):
    _by_id = {}

    @classmethod
    def getCache(cls):
        return cls._by_id

    def __init__(self, data, is_stub):
        super().__init__(data,is_stub)
        # Inconsistent data format, so have to mix two dicts
        self.user = User.get_or_construct({**{"id":data["user_id"]},**data["user"]},is_stub=False)
        if data["organization"]:
            self.org = Organization.get_or_construct({"id":data["org_id"],"name":data["organization"]["name"]})
            self.org.notes.append(self)
        if data["deal"]:
            self.deal = Deal.get_or_construct({"id":data["deal_id"],"name":data["deal"]["title"]},is_stub=True)
        if data["person"]:
            person_data = {"id": data["person_id"], "name": data["person"]["name"]}
            if data["organization"]:
                person_data["org_id"] = self.org.data
            self.person = Person.get_or_construct(person_data, is_stub=True)
            self.person.notes.append(self)

    def repr(self):
        return "(" + str(self.id)  + "," + str(self.content[0:30]) + ")"

class Activity(Entity):
    _by_id = {}

    @classmethod
    def getCache(cls):
        return cls._by_id

    def __init__(self, data, is_stub):
        super().__init__(data,is_stub)
        self.org = Organization.get_or_construct({"id":data["org_id"],"name":data["org_name"]})
        self.person = Person.get_or_construct({"id":data["person_id"],"name":data["person_name"],"org_id":self.org.data},is_stub=True)
        self.owner = User.get_or_construct({"id":data["user_id"],"name":data["owner_name"]},is_stub=True)

    def repr(self):
        return "(" + str(self.id)  + "," + str(self.subject) + ")"


class Client:
    flow_base_url = "https://oauth.pipedrive.com/oauth/"
    oauth_end = "authorize?"
    token_end = "token"
    api_version = "v1/"
    header = {"Accept": "application/json, */*", "content-type": "application/json"}

    _fields = ("client_id", "client_secret", "oauth", "api_base_url", "token")

    def __init__(self, api_base_url=None, client_id=None, client_secret=None, oauth=False):
        self.client_id = client_id
        self.client_secret = client_secret
        self.oauth = oauth
        self.api_base_url = api_base_url
        self.token = None
        if not api_base_url:
            self._load_settings()

    def _load_settings(self):
        data = json.load(open("pipedrive_settings.json", 'r'))
        for field in self._fields:
            if field in data:
                self.__setattr__(field,data[field])

    def _set_custom_fields(self):
        """
        Initialise the custom field data for all entities to allow attribute based access
        """
        print("Loading custom fields (from json cache files if possible)")
        regex = re.compile('[^0-9a-zA-Z]+')
        for entity in  EntityWithCustomFields.__subclasses__():
            file_name = entity.__name__ + "_custom_fields.json"
            try:
                f = open(file_name, 'r')
                entity.custom_fields = json.load(f)
                continue
            except:
                custom_fields = {}
                for field in self.get_entity_fields(entity)["data"]:
                    try:
                        int(field["key"],16) # test if it's hex
                        name=field["name"]
                        key=field["key"]
                        field_attr = regex.sub('_', name).lower()
                        custom_fields[field_attr] = {"key":key}
                        if "options" in field:
                            fields = {None:""}
                            for option in field["options"]:
                                fields[str(option["id"])] = option["label"]
                            custom_fields[field_attr]["fields"] = fields
                    except ValueError:
                        pass
                entity.custom_fields = custom_fields
                entity._by_id = dict()
                print("Set {} custom fields for {}.  Remove the json cache file ({}) to force reload next time."
                      .format(len(custom_fields),entity.__name__,file_name))
                with open(file_name, 'w') as f:
                    json.dump(custom_fields, f, ensure_ascii=False)

    def as_entity(self, entity, json):
        entities = self.as_entities(entity, json)
        if len(entities) > 1:
            raise Exception("Expected one " + entity.__name__ + " object, but " + str(len(entities)) + " were returned.")
        if entities:
            return entities[0]
        return None

    def as_entities(self, entity, json):
        data = json["data"]
        if not data:
            return {}
        if type(data) is dict:
            data = [data] # Convert singles to a list for ease
        return [entity.refresh_or_construct(e) for e in data]

    def make_request(self, method, endpoint, data=None, json=None, **kwargs):
        """
            this method do the request petition, receive the different methods (post, delete, patch, get) that the api allow
            :param method:
            :param endpoint:
            :param data:
            :param kwargs:
            :return:
        """
        if self.token:
            if self.oauth:
                self.header["Authorization"] = "Bearer " + self.token
                url = '{0}{1}{2}'.format(self.api_base_url, self.api_version, endpoint)
            else:
                url = '{0}{1}{2}?api_token={3}'.format(self.api_base_url, self.api_version, endpoint, self.token)
            if method == "get":
                response = requests.request(method, url, headers=self.header, params=kwargs)
            else:
                response = requests.request(method, url, headers=self.header, data=data, json=json)
            if not Entity.initialised:
                Entity.initialised = True # Must be set first to stop a infinite loop
                self._set_custom_fields()
            return self.parse_response(response)
        else:
            raise Exception("To make petitions the token is necessary")

    def _get(self, endpoint, data=None, **kwargs):
        return self.make_request('get', endpoint, data=data, **kwargs)

    def _post(self, endpoint, data=None, json=None, **kwargs):
        return self.make_request('post', endpoint, data=data, json=json, **kwargs)

    def _delete(self, endpoint, **kwargs):
        return self.make_request('delete', endpoint, **kwargs)

    def _put(self, endpoint, json=None, **kwargs):
        return self.make_request('put', endpoint, json=json, **kwargs)

    def parse_response(self, response):
        """
            This method get the response request and returns json data or raise exceptions
            :param response:
            :return:
        """
        if response.status_code == 204: # duplicate_deal returns data and is 201, removed or response.status_code == 201:
            return True
        elif response.status_code == 400:
            raise Exception(
                "The URL {0} retrieved an {1} error. Please check your request body and try again.\nRaw message: {2}".format(
                    response.url, response.status_code, response.text))
        elif response.status_code == 401:
            raise Exception(
                "The URL {0} retrieved and {1} error. Please check your credentials, make sure you have permission to perform this action and try again.".format(
                    response.url, response.status_code))
        elif response.status_code == 403:
            raise Exception(
                "The URL {0} retrieved and {1} error. Please check your credentials, make sure you have permission to perform this action and try again.".format(
                    response.url, response.status_code))
        elif response.status_code == 404:
            raise Exception(
                "The URL {0} retrieved an {1} error. Please check the URL and try again.\nRaw message: {2}".format(
                    response.url, response.status_code, response.text))
        elif response.status_code == 410:
            raise Exception(
                "The URL {0} retrieved an {1} error. Please check the URL and try again.\nRaw message: {2}".format(
                    response.url, response.status_code, response.text))
        elif response.status_code == 422:
            raise Exception(
                "The URL {0} retrieved an {1} error. Please check the URL and try again.\nRaw message: {2}".format(
                    response.url, response.status_code, response.text))
        elif response.status_code == 429:
            raise Exception(
                "The URL {0} retrieved an {1} error. Please check the URL and try again.\nRaw message: {2}".format(
                    response.url, response.status_code, response.text))
        elif response.status_code == 500:
            raise Exception(
                "The URL {0} retrieved an {1} error. Please check the URL and try again.\nRaw message: {2}".format(
                    response.url, response.status_code, response.text))
        elif response.status_code == 501:
            raise Exception(
                "The URL {0} retrieved an {1} error. Please check the URL and try again.\nRaw message: {2}".format(
                    response.url, response.status_code, response.text))
        return response.json()

    def get_oauth_uri(self, redirect_uri, state=None):
        if redirect_uri is not None:
            params = {
                'client_id': self.client_id,
                'redirect_uri': redirect_uri,
                # 'scope': ' '.join(scope),
            }
            if state is not None:
                params['state'] = state
            url = self.flow_base_url + self.oauth_end + urlencode(params)
            print(url)
            return url
        else:
            raise Exception("The attributes necessary to get the url were not obtained.")

    def exchange_code(self, redirect_uri, code):
        if redirect_uri is not None and code is not None:
            url = self.flow_base_url + self.token_end
            authorization = '{0}:{1}'.format(self.client_id, self.client_secret)
            header = {'Authorization': 'Basic {0}'.format(b64encode(authorization.encode('UTF-8')).decode('UTF-8'))}
            args = {'grant_type': 'authorization_code', 'code': code, 'redirect_uri': redirect_uri}
            response = requests.post(url, headers=header, data=args)
            return self.parse_response(response)
        else:
            raise Exception("The attributes necessary to exchange the code were not obtained.")

    def refresh_token(self, refresh_token):
        if refresh_token is not None:
            url = self.flow_base_url + self.token_end
            data = {
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'grant_type': "refresh_token",
                'refresh_token': refresh_token,
            }
            response = requests.post(url, data=data)
            return self.parse_response(response)
        else:
            raise Exception("The attributes necessary to refresh the token were not obtained.")

    def set_token(self, token):
        """
            Sets the Token for its use in this library.
            :param token:
            :return:
        """
        if token:
            self.token = token

    def get_recent_changes(self, **kwargs):
        """
            This method Returns data about all recent changes occured after given timestamp. in kwarg must to send "since_timestamp" with this format: YYYY-MM-DD HH:MM:SS
            :param kwargs:
            :return:
        """
        if kwargs is not None:
            url = "recents"
            return self._get(url, **kwargs)

    def get_data(self, endpoint, **kwargs):
        if endpoint != "":
            return self._get(endpoint, **kwargs)

    def get_specific_data(self, endpoint, data_id, **kwargs):
        if endpoint != "":
            url = "{0}/{1}".format(endpoint, data_id)
            return self._get(url, **kwargs)

    def create_data(self, endpoint, **kwargs):
        if endpoint != "" and kwargs is not None:
            params = {}
            params.update(kwargs)
            return self._post(endpoint, json=params)

    def _get_with_pagination(self, url, entity, **kwargs):
        entities = []
        while True:
            result = self._get(url, **kwargs)
            entities.extend(self.as_entities(entity, result))
            pagination = result["additional_data"]["pagination"]
            if pagination["more_items_in_collection"]:
                if "limit" in kwargs and kwargs["limit"] > pagination["next_start"]:
                    kwargs["start"] = pagination["next_start"]
                    print("Making another API hit for ", entity.__name__, ", starting at ", kwargs["start"])
                    continue
            break
        return entities

    def get_stages(self, **kwargs):
        """
        can pass in a pipeline_id to just get stages for one pipeline
        :param kwargs:
        :return:
        """
        url = "stages"
        return self.as_entities(Stage, self._get(url)) # No pagination here

    # Pipeline section, see the api documentation: https://developers.pipedrive.com/docs/api/v1/#!/Pipelines
    def get_pipelines(self, pipeline_id=None, **kwargs):
        if pipeline_id is not None:
            url = "pipelines/{0}".format(pipeline_id)
            return self.as_entity(Pipeline, self._get(url))
        else:
            url = "pipelines"
            return self.as_entities(Pipeline, self._get(url)) # No pagination here


    def get_pipeline_deals(self, pipeline_id, **kwargs):
        url = "pipelines/{0}/deals".format(pipeline_id)
        return self._get_with_pagination(url, Deal, **kwargs)

    # Deals section, see the api documentation: https://developers.pipedrive.com/docs/api/v1/#!/Deals
    def get_deals(self, deal_id=None, **kwargs):
        if deal_id is not None:
            url = "deals/{0}".format(deal_id)
            return self.as_entity(Deal, self._get(url))
        else:
            url = "deals"
        return self._get_with_pagination(url, Deal, **kwargs)

    def create_deal(self, **kwargs):
        url = "deals"
        if kwargs is not None:
            params = {}
            params.update(kwargs)
            return self.as_entity(Deal,self._post(url, json=params))

    def update_deal(self, deal_id, **kwargs):
        if deal_id is not None and kwargs is not None:
            url = "deals/{0}".format(deal_id)
            params = {}
            params.update(kwargs)
            return self.as_entity(Deal, self._put(url, json=params))

    def delete_deal(self, deal_id):
        if deal_id is not None:
            url = "deals/{0}".format(deal_id)
            return self._delete(url)

    def duplicate_deal(self, deal_id):
        if deal_id is not None:
            url = "deals/{0}/duplicate".format(deal_id)
            ret = self._post(url)
            print("duplicate_deal : ",ret)
            return self.as_entity(Deal,ret["data"])

    def get_deals_by_name(self, **kwargs):
        if kwargs is not None:
            url = "deals/find"
            return self._get_with_pagination(url, Deal, **kwargs)

    def get_deal_followers(self, deal_id):
        if deal_id is not None:
            url = "deals/{0}/followers".format(deal_id)
            return self._get(url)

    def add_follower_to_deal(self, deal_id, user_id):
        if deal_id is not None and user_id is not None:
            url = "deals/{0}/followers".format(deal_id)
            return self._post(url, json=user_id)

    def delete_follower_to_deal(self, deal_id, follower_id):
        if deal_id is not None and follower_id is not None:
            url = "deals/{0}/followers/{1}".format(deal_id, follower_id)
            return self._delete(url)

    def get_deal_participants(self, deal_id, **kwargs):
        if deal_id is not None:
            url = "deals/{0}/participants".format(deal_id)
            return self._get(url, **kwargs)

    def add_participants_to_deal(self, deal_id, person_id):
        if deal_id is not None and person_id is not None:
            url = "deals/{0}/participants".format(deal_id)
            return self._post(url, json=person_id)

    def delete_participant_to_deal(self, deal_id, participant_id):
        if deal_id is not None and participant_id is not None:
            url = "deals/{0}/participants/{1}".format(deal_id, participant_id)
            return self._delete(url)

    def get_deal_activities(self, deal_id, **kwargs):
        if deal_id is not None:
            url = "deals/{0}/activities".format(deal_id)
            return self.as_entities(Activity,self._get(url, **kwargs))

    def get_deal_mail_messages(self, deal_id, **kwargs):
        if deal_id is not None:
            url = "deals/{0}/mailMessages".format(deal_id)
            return self._get(url, **kwargs)

    def get_deal_products(self, deal_id, **kwargs):
        if deal_id is not None:
            url = "deals/{0}/products".format(deal_id)
            return self.as_entities(Deal,self._get(url, **kwargs))

    # Notes section, see the api documentation: https://developers.pipedrive.com/docs/api/v1/#!/Notes
    def get_notes(self, note_id=None, **kwargs):
        if note_id is not None:
            url = "notes/{0}".format(note_id)
            return self.as_entity(Note,self._get(url, **kwargs))
        else:
            url = "notes"
            return self._get_with_pagination(url, Note, **kwargs)

    def create_note(self, **kwargs):
        if kwargs is not None:
            url = "notes"
            params = {}
            params.update(kwargs)
            return self.as_entity(Note,self._post(url, json=params))

    def update_note(self, note_id, **kwargs):
        if note_id is not None and kwargs is not None:
            url = "notes/{0}".format(note_id)
            params = {}
            params.update(kwargs)
            return self.as_entity(Note,self._put(url, json=params))

    def delete_note(self, note_id):
        if note_id is not None:
            url = "notes/{0}".format(note_id)
            return self._delete(url)

    # Organizations section, see the api documentation: https://developers.pipedrive.com/docs/api/v1/#!/Organizations
    def get_organizations(self, org_id=None, **kwargs):
        """
        Returns either a single Organisation (if id specified), or a list otherwise.
        if the limit keyword is passed in, this will make multiple hits
        (collecting 500 per hit) until the limit is reached or all entities are retrieved
        :param org_id:
        :param kwargs:
        :return:
        """
        if org_id is not None:
            url = "organizations/{0}".format(org_id)
            return self.as_entity(Organization, self._get(url, **kwargs))
        else:
            url = "organizations"
            return self._get_with_pagination(url, Organization, **kwargs)


    def save_changes(self, entity):
        url = entity.__class__.__name__.lower() + "s/{0}".format(entity.id)
        params={}
        for field in entity.modified_fields:
            value = entity.data[field]
            if value == 'null':
                value = None
            params[field] = value
        print(params)
        return self.as_entity(entity.__class__,self._put(url,json=params))

    def create_organization(self, **kwargs):
        if kwargs is not None:
            url = "organizations"
            params = {}
            params.update(kwargs)
            return self._post(url, json=params)

    def update_organization(self, data_id, **kwargs):
        if data_id is not None:
            url = "organizations/{0}".format(data_id)
            params = {}
            params.update(kwargs)
            return self._put(url, json=params)

    def delete_organization(self, data_id):
        if data_id is not None:
            url = "organizations/{0}".format(data_id)
            return self._delete(url)

    def get_entity_fields(self,entityClass):
        url = "/" + entityClass.__name__.lower() + "Fields"
        return self._get(url)

    # Persons section, see the api documentation: https://developers.pipedrive.com/docs/api/v1/#!/Persons
    def get_persons(self, person_id=None, **kwargs):
        if person_id is not None:
            url = "persons/{0}".format(person_id)
            return self.as_entity(Person, self._get(url, **kwargs))
        else:
            url = "persons"
            return self._get_with_pagination(url, Person, **kwargs)


    def get_persons_by_name(self, **kwargs):
        if kwargs is not None:
            url = "persons/find"
            return self.as_entities(Person, self._get(url, **kwargs))


    def create_person(self, **kwargs):
        if kwargs is not None:
            url = "persons"
            params = {}
            params.update(kwargs)
            return self.as_entity(Person,self._post(url, json=params))

    def update_person(self, data_id, **kwargs):
        if data_id is not None and kwargs is not None:
            url = "persons/{0}".format(data_id)
            params = {}
            params.update(kwargs)
            return self.as_entity(Person,self._put(url, json=params))

    def delete_person(self, data_id):
        if data_id is not None:
            url = "persons/{0}".format(data_id)
            return self._delete(url)

    def get_person_deals(self, person_id, **kwargs):
        if person_id is not None:
            url = "persons/{0}/deals".format(person_id)
            return self.as_entities(Deal,self._get(url, **kwargs))

    # Products section, see the api documentation: https://developers.pipedrive.com/docs/api/v1/#!/Products
    def get_products(self, product_id=None, **kwargs):
        if product_id is not None:
            url = "products/{0}".format(product_id)
            return self.as_entity(Product,self._get(url, **kwargs))
        else:
            url = "products"
            return self.as_entities(Product,self._get(url, **kwargs))

    def get_product_by_name(self, params=None):
        if params is not None:
            url = "products/find"
            return self.as_entities(Product,self._get(url, params))

    def create_product(self, **kwargs):
        if kwargs is not None:
            url = "products"
            params = {}
            params.update(kwargs)
            return self.as_entity(Product,self._post(url, json=params))

    def update_product(self, product_id, **kwargs):
        if product_id is not None and kwargs is not None:
            url = "products/{0}".format(product_id)
            params = {}
            params.update(kwargs)
            return self.as_entity(Product,self._put(url, json=params))

    def delete_product(self, product_id):
        if product_id is not None:
            url = "products/{0}".format(product_id)
            return self._delete(url)

    def get_product_deals(self, product_id, **kwargs):
        if product_id is not None:
            url = "products/{0}/deals".format(product_id)
            return self.as_entities(Deal,self._get(url, **kwargs))

    # Activities section, see the api documentation: https://developers.pipedrive.com/docs/api/v1/#!/Activities
    def get_activities(self, activity_id=None, **kwargs):
        if activity_id is not None:
            url = "activities/{0}".format(activity_id)
        else:
            url = "activities"
        return self.as_entities(Activity,self._get(url, **kwargs))

    def create_activity(self, **kwargs):
        if kwargs is not None:
            url = "activities"
            params = {}
            params.update(kwargs)
            return self.as_entity(Activity,self._post(url, json=params))

    def update_activity(self, activity_id, **kwargs):
        if activity_id is not None:
            url = "activities/{0}".format(activity_id)
            params = {}
            params.update(kwargs)
            return self.as_entity(Activity,self._put(url, json=params))

    def delete_activity(self, activity_id):
        if activity_id is not None:
            url = "activities/{0}".format(activity_id)
            return self._delete(url)

    # Webhook section, see the api documentation: https://developers.pipedrive.com/docs/api/v1/#!/Webhooks
    def get_hooks_subscription(self):
        url = "webhooks"
        return self._get(url)

    def create_hook_subscription(self, subscription_url, event_action, event_object, **kwargs):
        if subscription_url is not None and event_action is not None and event_object is not None:
            args = {"subscription_url": subscription_url, "event_action": event_action, "event_object": event_object}
            if kwargs is not None:
                args.update(kwargs)
            return self._post(endpoint='webhooks', json=args)
        else:
            raise Exception("The attributes necessary to create the webhook were not obtained.")

    def delete_hook_subscription(self, hook_id):
        if hook_id is not None:
            url = "webhooks/{0}".format(hook_id)
            return self._delete(url)
        else:
            raise Exception("The attributes necessary to delete the webhook were not obtained.")
    
    # Users section, see the api documentation: https://developers.pipedrive.com/docs/api/v1/#!/Users
    def get_users(self, user_id=None, **kwargs):
        if user_id is not None:
            url = "users/{}".format(user_id)
            return self.as_entity(User,self._get(url, **kwargs))
        else:
            url = "users"
            return self.as_entities(User,self._get(url, **kwargs))
