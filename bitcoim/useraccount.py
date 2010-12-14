# -*- coding: utf-8 -*-
# vi: sts=4 et sw=4

from bitcoim.address import Address
from bitcoin.controller import Controller
from logging import debug, info, error
from db import SQL
from xmpp.jep0106 import JIDEncode
from xmpp.protocol import JID

FIELD_ID = 'id'
FIELD_JID = 'registered_jid'
FIELD_USERNAME = 'username'
TABLE_REG = 'registrations'

class UserAccount(object):
    '''Represents a user that's registered on the gateway.
       This class has a unique field: jid, which is the string
       representation of the user's bare JID.
    '''

    cacheByJID = {}
    cacheByUsername = {}

    def __new__(cls, name):
        '''Create the UserAccount instance, based on their JID.
           The jid variable must be of type JID. The resource is
           ignored, only the bare JID is taken into account.'''
        if 'JID' != name.__class__.__name__:
            if name in cls.cacheByUsername:
                return cls.cacheByUsername[name]
            req = "select %s from %s where %s=?" % (FIELD_JID, TABLE_REG, FIELD_USERNAME)
            SQL().execute(req, (name,))
            res = SQL().fetchone()
            if res is None:
                raise UnknownUserError
            else:
                username = name
                jid = res[0]
        else:
            username = None
            jid = name.getStripped()
        if jid not in cls.cacheByJID:
            cls.cacheByJID[jid] = object.__new__(cls)
            cls.cacheByJID[jid].jid = jid
            cls.cacheByJID[jid].resources = set()
            cls.cacheByJID[jid]._lastBalance = 0
            if username is None:
                username = cls.cacheByJID[jid]._updateUsername()
            if 0 != len(username):
                cls.cacheByUsername[username] = cls.cacheByJID[jid]
        return cls.cacheByJID[jid]

    def __str__(self):
        '''The textual representation of a UserAccount is the bare JID.'''
        return self.jid

    def __setattr__(self, name, value):
        '''Wrapper for username. Check if the requested username is available and change it.
           If the user is already registered, change their username in the database.
           If the username is invalid or taken, raise a UsernameNotAvailableError.'''
        if 'username' == name:
            username = value.strip()
            if self.canUseUsername(username):
                req = "update %s set %s=? where %s=?" % (TABLE_REG, FIELD_USERNAME, FIELD_JID)
                SQL().execute(req, (username, self.jid))
                object.__setattr__(self, 'username', username)
            else:
                raise UsernameNotAvailableError
        else:
            object.__setattr__(self, name, value)

    def _updateUsername(self):
        '''Fetch the username from the database and update the 'username'
           variable. For convenience, also return the result.
        '''
        req = "select %s from %s where %s=?" % (FIELD_USERNAME, TABLE_REG, FIELD_JID)
        SQL().execute(req, (self.jid,))
        res = SQL().fetchone()
        if res is None:
            object.__setattr__(self, 'username', '')
            return ''
        else:
            object.__setattr__(self, 'username', res[0])
            return res[0]

    def getLocalJID(self):
        '''Return the "local" (hosted at the gateway) JID of the user. The node
           of the JID is either the username or the real JID of the user,
           encoded according to XEP-0106 so that it can be used as a JID node.
        '''
        if 0 != len(self.username):
            name = self.username
        else:
            name = self.jid
        return JID(node=JIDEncode(name), domain=Address.domain)

    @staticmethod
    def getAllContacts():
        '''Return the list of all JIDs that are registered on the component.'''
        req = "select %s from %s" % (FIELD_JID, TABLE_REG)
        SQL().execute(req)
        result = SQL().fetchall()
        return [result[i][0] for i in range(len(result))]

    def canUseUsername(self, username):
        '''Is that username available to this user? For the moment, everything
           is valid except:
             - usernames already in use by anyone but the user
             - valid bitcoin addresses
        '''
        if Controller().validateaddress(username)['isvalid']:
            return False
        req = "select %s from %s where %s=? and %s!=?" % \
              (FIELD_ID, TABLE_REG, FIELD_USERNAME, FIELD_JID)
        SQL().execute(req, (username, self.jid))
        return SQL().fetchone() is None

    def isRegistered(self):
        '''Return whether a given JID is already registered.'''
        #TODO: Simply check whether this user has an address
        req = "select %s from %s where %s=?" % (FIELD_ID, TABLE_REG, FIELD_JID)
        SQL().execute(req, (unicode(self.jid),))
        return SQL().fetchone() is not None

    def register(self):
        '''Add given JID to subscribers if possible. Raise exception otherwise.
           If the UserAccount object already has a username, insert it.'''
        #TODO: Simply create an address for them
        if self.isRegistered():
            raise AlreadyRegisteredError
        info("Inserting entry for user %s into database" % self.jid)
        req = "insert into %s (%s, %s) values (?, ?)" % (TABLE_REG, FIELD_JID, FIELD_USERNAME)
        SQL().execute(req, (self.jid,self.username))

    def unregister(self):
        '''Remove given JID from subscribers if it exists. Raise exception otherwise.'''
        #TODO: Simply delete or change the account information on the user's address(es)
        debug("Deleting %s from registrations database" % self.jid)
        req = "delete from %s where %s=?" % (TABLE_REG, FIELD_JID)
        curs = SQL().execute(req, (self.jid,))
        if curs:
            count = curs.rowcount
            debug("%s rows deleted." % count)
            if 0 == count:
                info("User wanted to get deleted but wasn't found")
                raise AlreadyUnregisteredError
            elif 1 != count:
                error("We deleted %s rows when unregistering %s. This is not normal." % (count, jid))

    def resourceConnects(self, resource):
        self.resources.add(resource)

    def resourceDisconnects(self, resource):
        try:
            self.resources.remove(resource)
        except KeyError:
            pass # An "unavailable" presence is sent twice. Ignore.

    def getAddresses(self):
        '''Return the set of all addresses the user has control over'''
        return Controller().getaddressesbyaccount(self.jid)

    def getTotalReceived(self):
        '''Returns the total amount received on all addresses the user has control over.'''
        total =  Controller().getreceivedbyaccount(self.jid)
        debug("User %s has received a total of BTC %s" % (self.jid, total))
        return total

    def getRoster(self):
        '''Return the set of all the address JIDs the user has in her/his roster.
           This is different from the addresses the user has control over:
             - the user might want to ignore one of their own addresses,
               because there's no need to see them.
             - the user might want to see some addresses s/he doesn't own, in
               order to be able to easily send bitcoins to them.
             - they are JIDs, not bitcoin addresses.
        '''
        #TODO: Make it an independant list. As a placeholder, it's currently
        #      equivalent to getAddresses().
        roster = set()
        for addr in self.getAddresses():
            roster.add(Address(addr).jid)
        return roster

    def getBalance(self):
        '''Return the user's current balance'''
        return Controller().getbalance(self.jid)

    def checkBalance(self):
        '''Return the user's current balance if it has changed since last
           check, None otherwise.
        '''
        newBalance = self.getBalance()
        if newBalance == self._lastBalance:
            return None
        else:
            debug("%s's balance changed from %s to %s" % (self, self._lastBalance, newBalance))
            self._lastBalance = newBalance
            return newBalance

    def createAddress(self):
        '''Create a new bitcoin address, associate it with the user, and return it'''
        address = Address()
        info("Just created address %s. Associating it to user %s" % (address, self.jid))
        Controller().setaccount(address.address, self.jid)
        return address

    def ownsAddress(self, address):
        return self.jid == address.account

class AlreadyRegisteredError(Exception):
    '''A JID is already registered at the gateway.'''
    pass

class UsernameNotAvailableError(Exception):
    '''The requested username is already in use or is invalid.'''

class UnknownUserError(Exception):
    '''The user does not exist'''
