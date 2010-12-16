from logging import debug
from xmpp.protocol import JID as XJID

class JID(XJID):

    domain = ''

    def __init__(self, jid=None, node='', domain='', resource=''):
        '''This constructor allows the use of JID(node='foo'), since we do
           have a notion of default domain. If the default domain was not
           initialized, pyxmpp's JID will still raise a ValueError.'''
        if jid is None and ('' == domain):
            domain = self.domain
        XJID.__init__(self, jid, node, domain, resource)
