# -*- coding: utf-8 -*-
from lxml.objectify import parse
from django.conf import settings
from django.utils.translation import ugettext as _
from django.utils.translation import ugettext_lazy as _l
from django.utils.translation import get_language
import re
import random


# A catalog of the institution categories. The order in which they appear
# here is the same as they will appear on the web.
institution_categories =  settings.INSTITUTION_CATEGORIES

xpath_ns = {'ds': 'http://www.w3.org/2000/09/xmldsig#',
            'md': 'urn:oasis:names:tc:SAML:2.0:metadata',
            'mdrpi': 'urn:oasis:names:tc:SAML:metadata:rpi',
            'mdui': 'urn:oasis:names:tc:SAML:metadata:ui',
            'shibmd': 'urn:mace:shibboleth:metadata:1.0',
            'xi': 'http://www.w3.org/2001/XInclude',
            'xsi': 'http://www.w3.org/2001/XMLSchema-instance'}


class ShibbolethMetadata:
    """Basic object holding the shibboleth metadata"""

    def __init__(self,filename):
        """Initialize a ShibbolethMetadata object

        arguments:
            filename -- The location of the XML document containing Shibboleth metadata

        """

        self.mdtree = parse(filename)
        self.metadata = self.mdtree.getroot()

    def getEntities(self, entity_type = None, augmented=False):
        """Returns an EntityList holding all Entities (of requested type) found
        in the metadata, perhaps augmented in to the corresponding object type
        """
        if entity_type is "idp":
            entityfilter = "IDPSSODescriptor"
        elif entity_type is "sp":
            entityfilter = "SPSSODescriptor"
        # elif entity_type is "aa":
        #     entityfilter = "AttributeAuthorityDescriptor"
        else:
            entityfilter = None

        def filtertype(entity):
            if entityfilter is None:
                return True
            elif hasattr(entity, entityfilter):
                return True
            else:
                return False

        kots = filter(filtertype, self.metadata.xpath("//md:EntityDescriptor",
                                                     namespaces=xpath_ns))

        if augmented:
            return EntityList([ Entity.construct_augmented_entity(kot)
                                for kot in kots])
        else:
            return EntityList([ Entity(kot) for kot in kots])

    def getIdps(self):
        """Returns an IdpList holding all Identity Providers found in the metadata"""
        idps = self.getEntities("idp")

        return IdpList([ IdentityProvider.create_from_entity(kot) for kot in idps ])

    def getSps(self):
        """Returns an IdpList holding all Identity Providers found in the metadata"""
        sps = self.getEntities("sp")

        return SpList([ ServiceProvider.create_from_entity(kot) for kot in sps ])

    def getPath(self, entity):
        if isinstance(entity, Entity) and hasattr(entity, 'el'):
            return self.mdtree.getpath(entity.el)
        else:
            raise Exception('Can not get path for entity %s' % str(entity))


class EntityList(list):
    """Class holding a list of SAML Entities"""

    def __init__(self,entity_list):
        """Create a new list of SAML Entities

        arguments:
            entity_list -- a list of SAML Entities

        """
        list.__init__(self,entity_list)

    def __getitem__(self, key):
        # Allow for "entitylist['a_provider_entityid'] lookups
        try:
            return filter(lambda x: x.id == key, self)[0]
        except:
            return None

    def getGroups(self):
        """Returns the list of known groups entities are grouped by (in
        EntitiesDescriptor elements)

        """
        groups = set()
        for x in self:
            groups.update(x.groups)
        return groups

    def getEntities(self, lang=None, group=None, logosize=tuple()):
        """Returns a list of entities, where each entity is represented by a
        dict carrying the localized name, url, logo and entity ID attributes

        """
        if not lang:
            lang = get_language()

        if group:
            entities = filter(lambda x: group in x.groups, self)
        else:
            entities = self

        entities = sorted(entities)

        return map(lambda x: {'name': x.getName(lang),
                              'url': x.getURL(lang),
                              'logo': x.getLogo(targetsize=logosize),
                              'id': x.id },
                   entities)

    def getEntitiesByGroup(self, lang=None, exclude=[]):
        """Returns a sequence of tuples of the form:

        (group, [ entity1, entity2, ...])

        where the second element of each tuple is the return value of
        getEntities()

        """
        groups = filter(lambda x: x not in exclude, self.getGroups())

        entities = []
        for group in groups:
            entities.append(self.getEntities(lang=lang, group=group))

        return zip(groups, entities)


class IdpList(EntityList):
    """Class holding a list of SAML Identity Providers"""

    def __init__(self,idplist):
        """Create a new list of Identity Providers

        arguments:
            idplist -- a list of IdentityProvider instances

        """
        super(EntityList, self).__init__(idplist)

    def getCategories(self):
        """Returns the list of known categories of Identity Providers"""

        return sorted(set(map(lambda x: x.getType(), self)))

    def getCategoryIdps(self, category):
        """Returns the list of known identity providers for a given category"""

        return filter(lambda x: x.getType() == category, self)

    def getIdpForScope(self, scope):
        """Returns the identity provider matching a given scope"""

        try:
            return filter(lambda x: x.matchesScope(scope), self)[0]
        except:
            return None

    def getIdpsByCategory(self, lang=None, exclude=None):
        """Returns a sequence of tuples of the form:

        (category, [ idp1, idp2, ...])

        where idpX is a dict { 'name': name, 'id': entityid }

        The list of idps is sorted by name

        """
        if not lang:
            lang = get_language()

        if exclude:
            validcats = filter(lambda x: x[0] not in exclude, institution_categories)
        else:
            validcats = institution_categories

        cats = map(lambda x: x[0], validcats)

        categories = map(lambda x: { 'id': x[0], 'name': _l(x[1]) }, validcats)

        idps = []

        for category in cats:
            catidps = sorted(self.getCategoryIdps(category))
            idps.append(map(lambda x: {
                    'name': x.getName(lang),
                    'url': x.getURL(lang),
                    'id': x.id },
                    catidps))

        return zip(categories, idps)


class SpList(EntityList):
    """Class holding a list of SAML Service Providers"""

    def __init__(self,splist):
        """Create a new list of Service Providers

        arguments:
            splist -- a list of ServiceProvider instances

        """
        super(EntityList, self).__init__(splist)


class Entity:
    """Basic class holding a SAML Entity"""

    def __init__(self,el):
        """Create a new Entity instance
        arguments:
            el -- An lxml.objectify.Element holding an EntityDescriptor for a SAML Entity

        """

        self.el = el
        self.name = {} # Holds the Entity's name in a form { language: string }
        self.url = {}
        self.logo = {}
        self.id = self.el.get('entityID')
        self.groups = set(el.xpath("ancestor::md:EntitiesDescriptor/@Name", namespaces=xpath_ns))

        # Initialize the contact details
        self.contact = { 'givenName': '', 'surName': '', 'company': '', 'email': '', 'telephone': '', 'url': '' }

        # Get the institution's name
        try:
            for name in self.el.Organization.OrganizationDisplayName:
                self.name[name.get('{http://www.w3.org/XML/1998/namespace}lang')] = name.text
        except:
            self.name = {'en': "no name"}

        try:
            for url in self.el.Organization.OrganizationURL:
                self.url[url.get('{http://www.w3.org/XML/1998/namespace}lang')] = url.text
        except:
            pass

        # Fill in the contact details
        try:
            for contact in self.el.ContactPerson:
                if contact.get('contactType') == "support":
                    # We're not sure these details even exists, but since that would
                    # require a set of nested checks, exception catching is more
                    # clean.
                    try:
                        self.contact['email'] = contact.EmailAddress.text
                    except:
                        pass

                    try:
                        self.contact['telephone'] = contact.TelephoneNumber.text
                    except:
                        pass
        except:
            pass

    def __cmp__ (self,other):
        # Alphabetic sorting by name
        return cmp(self.getName(get_language()), other.getName(get_language()))

    def __repr__(self):
        return "Entity: \"" + self.name['en'] + '" (' + self.id + ')'

    @classmethod
    def create_from_entity(cls, entity):
        if issubclass(cls, entity.__class__) and hasattr(entity, 'el'):
            return cls(entity.el)
        else:
            raise Exception('Can not instantiate %s from %s' % (cls,
                                                                str(entity)))

    @staticmethod
    def construct_augmented_entity(el):
        elcls = el.__class__
        # should do isinstance() but we do not import whole lxl.objectify
        if ("%s.%s" % (elcls.__module__, elcls.__name__)) == \
                "lxml.objectify.ObjectifiedElement":
            if hasattr(el, "IDPSSODescriptor"):
                aug_ent_cls = IdentityProvider
            elif hasattr(el, "SPSSODescriptor"):
                aug_ent_cls = ServiceProvider
            # elif hasattr(el, "AttributeAuthorityDescriptor"):
            #     pass
            else:
                aug_ent_cls = None

            if aug_ent_cls is not None:
                return aug_ent_cls(el)

        raise Exception("Can not instantiate augmented Entity from %s" %
                             el)

    def getName(self,lang=None):
        if not lang:
            lang = get_language()

        try:
            return self.name[lang]
        except:
            try:
                return self.name['en']
            except:
                return self.name[self.name.keys()[0]]

    def getURL(self,lang=None):
        if not lang:
            lang = get_language()

        try:
            return self.url[lang]
        except:
            pass

        try:
            return self.url['en']
        except:
            pass

        return None

    def getLogo(self,targetsize=tuple()):

        if not self.logo:
            return None

        # get (x, y) closest to target (a, b)
        if isinstance(targetsize, tuple) and \
                len(targetsize) is 2 and \
                [isinstance(i, int) for i in targetsize]:
            dimensions = min(self.logo.keys(),
                             key = lambda x: abs(x[0]-targetsize[0]) + \
                                 abs(x[1]-targetsize[1])
                             )
        else:
            dimensions = random.choice(self.logo.keys())

        return { 'width': dimensions[0],
                 'height': dimensions[1],
                 'data': self.logo[dimensions] }


class IdentityProvider(Entity):
    """Class holding a SAML Identity Provider"""

    def __init__(self,idpel):
        """Create a new IdentityProvider instance
        arguments:
            idpel -- An lxml.objectify.Element holding an EntityDescriptor for a shibboleth IdP

        """

        Entity.__init__(self, idpel)

        # Dictionary to hold all ArtifactResolutionService definitions, by Binding
        self.ars = {}
        # Dictionary to hold all SingleLogoutService definitions, by Binding
        self.slo = {}
        # Dictionary to hold all ManageNameIDService definitions, by Binding
        self.mnid = {}
        # Dictionary to hold all SingleSignOnService definitions, by Binding
        self.sso = {}

        # Get all SingleSignOnService definitions (required)
        for entry in self.el.IDPSSODescriptor.SingleSignOnService:
            self.sso[entry.get('Binding')] = entry.get('Location')
        try:
            # Get all SingleLogoutService definitions
            for entry in self.el.IDPSSODescriptor.SingleLogoutService:
                self.slo[entry.get('Binding')] = entry.get('Location')
            # Get all ArtifactResolutionService definitions
            for entry in self.el.IDPSSODescriptor.ArtifactResolutionService:
                self.ars[entry.get('Binding')] = entry.get('Location')
            # Get all ManageNameIDService definitions
            for entry in self.el.IDPSSODescriptor.ManageNameIDService:
                self.mnid[entry.get('Binding')] = entry.get('Location')
        except:
            pass

        # Override self.name, self.url with mdui:DisplayName, mdui:DisplayName
        # also add logo from mdui:Logo
        try:
            ui = self.el.IDPSSODescriptor.\
                Extensions['{urn:oasis:names:tc:SAML:metadata:ui}UIInfo']
            # Override self.name with mdui:DisplayName or self.atcs.name
            if hasattr(ui, 'DisplayName'):
                self.name = {}
                for name in ui.DisplayName:
                    self.name[name.get(
                            '{http://www.w3.org/XML/1998/namespace}lang'
                            )] = name.text
            # Override self.url with mdui:InformationURL
            if hasattr(ui,'InformationURL'):
                self.url = {}
                for url in ui.InformationURL:
                    self.url[url.get(
                            '{http://www.w3.org/XML/1998/namespace}lang'
                            )] = url.text
            # Also add logo from mdui:Logo
            if hasattr(ui, 'Logo'):
                for logo in ui.Logo:
                    self.logo[(int(logo.get('width')),
                               int(logo.get('height')))] = logo.text
        except:
            pass

    def __repr__(self):
        return "IDP: \"" + self.name['en'] + '" (' + self.id + ')'

    def getType(self):
        """Returns the type (category) of the current IdP"""

        # Some heuristics to determine the IdP type, based on the
        # institution's name in english.
        for lang in self.name.values():
            if lang.lower().find('test') >= 0:
                return "test"
            elif re.findall(r'(univerisyt|universiteit|universite|school of fine arts)', lang.lower()):
                return "university"
            elif lang.lower().find('technological') >= 0:
                return "tei"
            elif re.findall(r'(ecclesiastical|school|academy)', lang.lower()):
                return "school"
            elif re.findall(r'(institute|cent(er|re)|ncsr|foundat|bservat)', lang.lower()):
                return "institute"
        return "other"

    def getScope(self):
        """Returns the scope of the current IdP"""

        scopes = filter(lambda x: x.tag == "{urn:mace:shibboleth:metadata:1.0}Scope", self.el.IDPSSODescriptor.Extensions.getchildren())
        return scopes[0].text

    def matchesScope(self,scope):
        """Checks wheter the current IdPs scope matches the given string"""

        myscope = self.getScope()

        # Append a trailing '$', to align the regexp with the string end
        if myscope[-1] != '$':
            myscope += '$'

        if re.search(myscope, scope):
            return True

        return False


class ServiceProvider(Entity):
    """Class holding a SAML Service Provider"""

    def __init__(self,spel):
        """Create a new ServiceProvider instance
        arguments:
            spel -- An lxml.objectify.Element holding an EntityDescriptor for a shibboleth SP

        """

        Entity.__init__(self, spel)

        # Dictionary to hold all AssertionConsumerService definitions, by Binding
        self.acs = {}
        # Dictionary to hold all SingleLogoutService definitions, by Binding
        self.slo = {}
        # Dictionary to hold all ManageNameIDService definitions, by Binding
        self.mnid = {}
        # Dictionary to hold all AttributeConsumingService definitions, by ServiceName
        self.atcs = {}

        # Get all AssertionConsumerService definitions (required)
        for entry in self.el.SPSSODescriptor.AssertionConsumerService:
            self.acs[entry.get('Binding')] = entry.get('Location')
        # Get all SingleLogoutService definitions
        try:
            for entry in self.el.SPSSODescriptor.SingleLogoutService:
                self.slo[entry.get('Binding')] = entry.get('Location')
        except:
            pass
        # Get all ManageNameIDService definitions
        try:
            for entry in self.el.SPSSODescriptor.ManageNameIDService:
                self.mnid[entry.get('Binding')] = entry.get('Location')
        except:
            pass
        # Get all AttributeConsumingService definitions
        try:
            for entry in self.el.SPSSODescriptor.AttributeConsumingService:
                atcs_name = {}
                if hasattr(entry, 'ServiceName'):
                    for name in entry.ServiceName:
                        atcs_name[name.get(
                                '{http://www.w3.org/XML/1998/namespace}lang'
                                )] = name.text
                atcs_descr = {}
                if hasattr(entry, 'ServiceDescription'):
                    for descr in entry.ServiceDescription:
                        atcs_descr[descr.get(
                                '{http://www.w3.org/XML/1998/namespace}lang'
                                )] = descr.text
                req_attr = {}
                if hasattr(entry, 'RequestedAttribute'):
                    for attr in entry.RequestedAttribute:
                        req_attr[(attr.get('Name'),
                                  attr.get('NameFormat'))] = {
                            'name': attr.get('FriendlyName'),
                            'required':
                                True if \
                                attr.get('isRequired').lower == 'true' \
                                else False
                            }
                if 'en' in atcs_name:
                    self.atcs[atcs_name['en']] = type(
                        self.__class__.__name__ + \
                            '.AttributeConsumingService',
                        (object,),
                        { 'name': atcs_name,
                          'descr': atcs_descr,
                          'attr': req_attr }
                        )
        except AttributeError:
            pass

        # Override self.name with self.atcs.name
        if self.atcs:
            self.name = [s.name for s in self.atcs.values()][0]

        try:
            ui = self.el.SPSSODescriptor.\
                Extensions['{urn:oasis:names:tc:SAML:metadata:ui}UIInfo']
            # Override self.name with mdui:DisplayName
            if hasattr(ui, 'DisplayName'):
                self.name = {}
                for name in ui.DisplayName:
                    self.name[name.get(
                            '{http://www.w3.org/XML/1998/namespace}lang'
                            )] = name.text
            # Override self.url with mdui:InformationURL
            if hasattr(ui,'InformationURL'):
                self.url = {}
                for url in ui.InformationURL:
                    self.url[url.get(
                            '{http://www.w3.org/XML/1998/namespace}lang'
                            )] = url.text
            # Also add logo from mdui:Logo
            if hasattr(ui, 'Logo'):
                for logo in ui.Logo:
                    self.logo[(int(logo.get('width')),
                               int(logo.get('height')))] = logo.text
        except AttributeError:
            pass

    def __repr__(self):
        return "SP: \"" + self.name['en'] + '" (' + self.id + ')'
