# -*- coding: utf-8 -*-
# vi: sts=4 et sw=4

from bitcoim.address import Address
from bitcoin.controller import Controller
from logging import debug, info, error
from db import SQL
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

    cache = {}

    def __new__(cls, jid):
        '''Create the UserAccount instance, based on their JID.
           The jid variable must be of type JID. The resource is
           ignored, only the bare JID is taken into account.'''
        jid = jid.getStripped()
        if jid not in cls.cache:
            debug("Creating new UserAccount in cache for %s" % jid)
            cls.cache[jid] = object.__new__(cls)
            cls.cache[jid].jid = jid
            cls.cache[jid]._username = None
            cls.cache[jid].resources = set()
            cls.cache[jid]._lastBalance = 0
        debug("Returning UserAccount(%s)" % jid)
        return cls.cache[jid]

    def __str__(self):
        '''The textual representation of a UserAccount is the bare JID.'''
        return self.jid

    def __getattr__(self, name):
        if 'username' == name:
            if self._username is None:
                req = "select %s from %s where %s=?" % (FIELD_USERNAME, TABLE_REG, FIELD_JID)
                SQL().execute(req, (self.jid,))
                res = SQL().fetchone()
                if res is None:
                    self._username = ''
                else:
                    self._username = res[0]
            return self._username
        else:
            return object.__getattr__(self, name)

    def __setattr__(self, name, value):
        '''Wrapper for username. Check if the requested username is available and change it.
           If the user is already registered, change their username in the database.
           If the username is invalid or taken, raise a UsernameNotAvailableError.'''
        if 'username' == name:
            if self.usernameIsAvailable(value):
                req = "update %s set %s=? where %s=?" % (TABLE_REG, FIELD_USERNAME, FIELD_JID)
                SQL().execute(req, (value, self.jid))
                self._username = value
            else:
                raise UsernameNotAvailableError
        else:
            object.__setattr__(self, name, value)

    @staticmethod
    def getAllContacts():
        '''Return the list of all JIDs that are registered on the component.'''
        req = "select %s from %s" % (FIELD_JID, TABLE_REG)
        SQL().execute(req)
        result = SQL().fetchall()
        return [result[i][0] for i in range(len(result))]

    def usernameIsAvailable(self, username):
        '''Is that username available? NOTE: Current implementation is a
           placeholder. It always return True.'''
        return True

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

class AlreadyUnregisteredError(Exception):
    '''An unregisration was asked but the JID wasn't registered at the gateway.'''
    pass

class UsernameNotAvailableError(Exception):
    '''The requested username is already in use or is invalid.'''
