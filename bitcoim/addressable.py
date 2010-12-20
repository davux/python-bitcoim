from bitcoim import LIB_NAME, LIB_VERSION
from bitcoin.address import InvalidBitcoinAddressError
from jid import JID
from logging import debug
from xmpp.jep0106 import JIDDecode
from xmpp.protocol import Presence, NodeProcessed, NS_LAST, NS_VERSION, \
                          NS_DISCO_INFO
from xmpp.simplexml import Node

'''
   This module represent any object that is addressable in the scope of the
   component.
'''

def generate(jid, components, requester):
    '''Generate the appropriate Addressable object depending on the JID given
       as argument. The 'components' argument is a list of component
       instances to try. If the requester is an admin , allow resolution of
       the entity as a JID, otherwise only look it up as a username. '''
    from address import Address
    from useraccount import UserAccount, UnknownUserError
    for component in components:
        if component.jid == jid.getStripped():
            return component
    try:
        return Address(jid)
    except InvalidBitcoinAddressError:
        try:
            jidprefix = JIDDecode(jid.getNode())
            if requester.isAdmin() and (0 <= jidprefix.find('.')):
                # Treat as JID, and must be registered
                return UserAccount(JID(jidprefix), True)
            else:
                # Treat as username
                return UserAccount(jidprefix)
        except UnknownUserError:
            return None

# Time of last activity (XEP-0012)
last = None

class Addressable(object):
    '''An addressable object'''

    def discoReceived(self, user, what, node=None):
        '''Default method, sends nothing interesting.
           - user: the UserAccount doing the request
           - what: 'info' or 'items'
           - node: what node was requested
        '''
        if 'info' == what:
            ids = [{'category': 'hierarchy', 'type': 'leaf'}]
            return {'ids': ids, 'features': [NS_DISCO_INFO]}

    def iqReceived(self, cnx, iq):
        '''Default handler for IQ stanzas.'''
        typ = iq.getType()
        ns = iq.getQueryNS()
        if (NS_VERSION == ns) and ('get' == typ):
            name = Node('name')
            name.setData(LIB_NAME)
            version = Node('version')
            version.setData(LIB_VERSION)
            reply = iq.buildReply('result')
            query = reply.getQuery()
            query.addChild(node=name)
            query.addChild(node=version)
            cnx.send(reply)
            raise NodeProcessed
        elif (NS_LAST == ns) and ('get' == typ):
            if self.last is not None:
                reply = iq.buildReply('result')
                query = reply.getQuery()
                query.setAttr('seconds', (datetime.now() - self.last).seconds)
                cnx.send(reply)
                raise NodeProcessed
        else:
            debug("Unhandled IQ namespace '%s'." % ns)
