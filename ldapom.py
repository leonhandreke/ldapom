#! /usr/bin/python
# -*- coding: utf-8 -*-
"A LDAP object-mapper"

# Copyright (c) 2010 Florian Richter <mail@f1ori.de>
# 
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
# 
# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
# OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
# IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
# CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
# TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

import ldap

# decorators
def _retry_on_disconnect(func):
    "decorator to handle disconnection"
    def new(self, *args, **kws):
        "wrapper function, catching the exception"
        try:
            return func.__call__(self, *args, **kws)
        except ldap.SERVER_DOWN:
            # try to reconnect
            self._connect()
        return func(self, *args, **kws)
    return new

def _retry_on_disconnect_gen(func):
    "decorator for generator functions to handle disconnection"

    def new(self, *args, **kws):
        """
                wrapper function, catching the exception
                (acting as generator function)
        """
        try:
            gen = func(self, *args, **kws)
            yield gen.next()
        except ldap.SERVER_DOWN:
            # try to reconnect
            self._connect()
            gen = func(self, *args, **kws)
        while 1:
            yield gen.next()
        # return via StopIteration-exception

    return new

class LdapConnection(object):
    """
        This Object holds all parameters to connect to an ldapserver
        and provide a minimal convenience.
        Methods marked as internal in the docstring should be used only
        by this modul.

        Methods for external relevance so far:
        * __init__
        * getLdapNode
    """

    def __init__(self, uri, base, login, password):
        self._lo = None # ldap-connection
        self._uri = uri
        self._base = base
        self._login = login
        self._password = password
        self._connect()
        self._timeout = 0

    def _connect(self):
        "connect to ldap-server"
        self._lo = ldap.initialize(self._uri)
        # TODO:tls
        #self._lo.set_option(ldap.OPT_X_TLS_DEMAND, False)
        self._lo.simple_bind_s(self._login, self._password)

    def authenticate(self, dn, password):
        "Internal: try to authenticate on a seperate connection"
        lo = ldap.initialize(self._uri)
        # TODO:tls
        try:
            res_type, res_data = lo.simple_bind_s(dn, password)
            return res_type == ldap.RES_BIND
        except ldap.INVALID_CREDENTIALS:
            return False

    @_retry_on_disconnect
    def add(self, dn, attrs):
        "Internal: raw ldap add function"
        res_type, res_data = self._lo.add_s(dn, attrs)
        if res_type != ldap.RES_ADD:
            raise ldap.LDAPError, "Wrong result type"

    @_retry_on_disconnect
    def modify(self, dn, change):
        "Internal: raw ldap modify function"
        res_type, res_data = self._lo.modify_s(dn, change)
        if res_type != ldap.RES_MODIFY:
            raise ldap.LDAPError, "Wrong result type"


    @_retry_on_disconnect
    def delete(self, dn):
        "Internal: raw ldap delete function"
        res_type, res_data = self._lo.delete_s(dn)
        if res_type != ldap.RES_DELETE:
            raise ldap.LDAPError, "Wrong result type"

    @_retry_on_disconnect_gen
    def query(self, filter="(objectClass=*)", retrieve_attributes=None, base=None,
                scope=ldap.SCOPE_SUBTREE):
        "Internal: convencience wrapper arround ldap search"
        if base == None:
            base = self._base
        result_id = self._lo.search(base, scope, filter, retrieve_attributes)
        while 1:
            result_type, result_data = self._lo.result(result_id, self._timeout)
            if (result_data == []):
                break
            else:
                if result_type == ldap.RES_SEARCH_ENTRY:
                    yield result_data[0]

    def check_if_dn_exists(self, dn):
        "search ldap-server for dn and return a boolean"
        try:
            res = self.query(base=dn, scope=ldap.SCOPE_BASE)
            if len(list(res)) != 0:
                return True
        except ldap.NO_SUCH_OBJECT:
            return False
        return False

    def get_ldap_node(self, dn):
        "Create LdapNode-Object linked to this connection"
        return LdapNode(self, dn)

    def new_ldap_node(self, dn):
        "Create new LdapNode-Object linked to this connection"
        return LdapNode(self, dn, new=True)

class LdapAttribute(object):
    """
        Holds an set of LDAP-Attributes with the same name.
        All changes are recorded, so they can be push to ldap_modify
        directly
    """

    def __init__(self, name, value, add=False):
        self._name = name
        self._replace_all = False
        self._added = []
        if add:
            self._values = []
            if type(value) == list:
                for v in value:
                    self.append(v)
            else:
                self.append(value)
        else:
            if type(value) == list:
                self._values = value
            else:
                self._values = [str(value)]

    def __len__(self):
        return len(self._values)

    def __str__(self):
        "if there's only one item, return it directly"
        if len(self._values) == 1:
            return self._values[0]
        return str(self._values)

    def __repr__(self):
        return "<LdapAttribute: %s=%s>" % (self._name, self.__str__())

    def append(self, value):
        "add an attribute"
        if not value in self._values:
            self._values.append(str(value))
            self._added.append((ldap.MOD_ADD, self._name, str(value)))

    def __contains__(self, item):
        return self._values.__contains__(item)

    def __getitem__(self, key):
        return self._values[key]

    def __setitem__(self, key, value):
        self._replace_all = True
        self._values[key] = str(value)

    def __delitem__(self, key):
        self._replace_all = True
        del self._values[key]

    def __iter__(self):
        return self._values.__iter__()

    def set_value(self, value):
        "set single value, discard all existing ones"
        if type(value) == list:
            self._values = value
        else:
            self._values = [str(value)]
        self._replace_all = True

    def get_change_list(self):
        "get all changes to this attribute in ldap_modify-syntax"
        if self._replace_all:
            if len(self) == 0:
                return (ldap.MOD_DELETE, self._name, None)
            change_list = [ (ldap.MOD_REPLACE, self._name, x) for x in self._values[0:1]]
            change_list += [ (ldap.MOD_ADD, self._name, x) for x in self._values[1:] ]
            return change_list
        return self._added

    def discard_change_list(self):
        "called when attribute-changes were successfully saved"
        self._added = []
        self._replace_all = False


class LdapNode(object):
    """
        Holds an ldap-object represented by the dn (distinguishable name).
        attributes are fetched from ldapserver lazily, so you can create objects
        without network traffic.
    """

    def __init__(self, conn, dn, new=False):
        "Create lazy Node Object from dn"
        self._conn = conn
        self._dn = dn
        self._valid = True
        self._to_delete = []
        self._new = new
        if new:
            self._attr = {}
        else:
            self._attr = None

    def __getattr__(self, name):
        """
            get an ldap-attribute lazyly
            * attributes starting with is_* are mapped to a check, if the objectClass is present
        """
        if self._attr == None:
            # query attributes
            attr = list(self._conn.query(base=self._dn, scope=ldap.SCOPE_BASE))[0][1]
            # wrap them into LdapAttribute objects
            self._attr = dict([ (x[0], LdapAttribute(x[0], x[1])) for x in attr.items() ])
        if name.startswith("is_"):
            return name[3:] in self._attr["objectClass"]
        if name in self._attr:
            return self._attr[name]
        else:
            raise AttributeError

    def __setattr__(self, name, value):
        "set ldap attribute"
        # handle private attributes the default way
        if name.startswith("_"):
            return object.__setattr__(self, name, value)
        if self._attr == None:
            # query attributes
            attr = list(self._conn.query(base=self._dn, scope=ldap.SCOPE_BASE))[0][1]
            # wrap them into LdapAttribute objects
            self._attr = dict([ (x[0], LdapAttribute(x[0], x[1])) for x in attr.items()])
        if name in self._attr:
            self._attr[name].set_value(value)
        else:
            self._attr[name] = LdapAttribute(name, value, add=True)

    def __delattr__(self, name):
        if self._attr == None:
            # query attributes
            attr = list(self._conn.query(base=self._dn, scope=ldap.SCOPE_BASE))[0][1]
            # wrap them into LdapAttribute objects
            self._attr = dict([ (x[0], LdapAttribute(x[0], x[1])) for x in attr.items() ])
        del self._attr[name]
        self._to_delete.append(name)

    def __str__(self):
        return self._dn

    def __repr__(self):
        return "<LdapNode: %s>" % self._dn

    def save(self):
        """Save any changes to the object"""
        if self._new:
            change_list = [ (x._name, x._values) for x in self._attr.values() ]
            print "ldap_add: %s" % change_list
            self._conn.add(self._dn, change_list)
        else:
            change_list = [ (ldap.MOD_DELETE, x, None) for x in self._to_delete ]
            for attr in self._attr.values():
                change_list.extend(attr.get_change_list())
            if len(change_list) == 0:
                return
            print "ldap_modify: %s" % change_list
            self._conn.modify(self._dn, change_list)
        self._new = False
        self._to_delete = []
        for attr in self._attr.values():
            attr.discard_change_list()

    def delete(self):
        "delete this object in ldap"
        self._conn.delete(self._dn)
        self._valid = False

    def check_password(self, password):
        "check password for this ldap-object"
        return self._conn.authenticate( self._dn, password ) 

    def set_password(self, password):
        "set password for this ldap-object"
        # TODO: implemement encryption with crypt
        self.__setattr__('userPassword', password)


# vim: ai sw=4 expandtab