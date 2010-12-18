from bitcoin.address import InvalidBitcoinAddressError
from xmpp.jep0106 import JIDDecode
from xmpp.protocol import NS_DISCO_INFO

'''
   This module represent any object that is addressable in the scope of the
   component.
'''

def generate(jid, components, onlyUsernames=True):
    '''Generate the appropriate Addressable object depending on the JID given
       as argument. The 'components' argument is a list of component
       instances to try. The 'onlyUsername' attributes determines whether the
       node part of the JID can represent a full JID or only a username. '''
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
            if onlyUsernames or (-1 == to.getNode().find('.')):
                # Treat as username
                return UserAccount(jidprefix)
            else:
                # Treat as JID, and must be registered
                return UserAccount(JID(jidprefix), True)
        except UnknownUserError:
            return None


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
            name.setData(APP_NAME)
            version = Node('version')
            version.setData(APP_VERSION)
            reply = iq.buildReply('result')
            query = reply.getTag('query')
            query.addChild(node=name)
            query.addChild(node=version)
            cnx.send(reply)
            raise NodeProcessed
        elif (NS_LAST == ns) and ('get' == typ):
            frm = iq.getTo().getNode()
            if frm in self.last:
                reply = iq.buildReply('result')
                query = reply.getTag('query')
                query.setAttr('seconds', (datetime.now() - self.last[frm]).seconds)
                cnx.send(reply)
                raise NodeProcessed
        else:
            debug("Unhandled IQ namespace '%s'." % ns)
