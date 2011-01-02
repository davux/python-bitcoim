from addressable import Addressable
from bitcoin.address import Address as BCAddress
from i18n import _, DISCO, DEFAULT, ROSTER
from jid import JID
from paymentorder import PaymentOrder
from xmpp.protocol import Presence, NodeProcessed, NS_VCARD, NS_VERSION, \
                          NS_DISCO_INFO, NS_DISCO_ITEMS

ENCODING_SEP = '-'
ENCODING_BASE = 36 # Any value from 2 to 36 would work - smaller values produce longer suffixes

class Address(Addressable, BCAddress):
    '''A Bitcoin address, but with some xmpp-specific capabilities. In particular, it has
       a 'jid' attribute that represents is encoding as a JID. Reciprocally, it's possible
       to construct an address with a JID.
    '''

    def __init__(self, address=None):
        '''Constructor. Initialize a bitcoin address normally.
           If the argument is a JID object, though, decode it first.
        '''
        self._jid = None
        self._owner = None
        if 'JID' == address.__class__.__name__:
            address.setResource('')
            self._jid = address
            address = address.getNode()
            parts = address.partition(ENCODING_SEP)
            if len(parts[2]):
                positions = int(parts[2], ENCODING_BASE)
                address = ''
                for c in reversed(parts[0]):
                    if c.isalpha():
                        if (positions % 2):
                            c = c.upper()
                        positions //= 2
                    address = c + address
        BCAddress.__init__(self, address)

    def __getattr__(self, name):
        if 'jid' == name:
            if self._jid is None: # Wait first call to compute it
                # 1DXFn72VHrXRVYJTTxjbmNXyXpYXmgiWfw
                # 1dxfn72vhrxrvyjttxjbmnxyxpyxmgiwfw (lowercase)
                # 1110  110111111100001101011000100 (mask on uppercase)
                # -> mask in base36 (should return x0l0p0)
                mask = long(0)
                gaps = 0
                for i, char in enumerate(reversed(self.address)):
                    if char.isupper():
                        mask += 2 ** (i - gaps)
                    elif char.isdigit():
                        gaps += 1
                suffix = ""
                while mask > 0:
                    suffix = "0123456789abcdefghijklmnopqrstuvwxyz"[mask % ENCODING_BASE] + suffix
                    mask //= ENCODING_BASE
                if ("" != suffix):
                    suffix = ENCODING_SEP + suffix
                self._jid = JID(node=self.address.lower() + suffix)
            return self._jid
        elif 'owner' == name:
            if self._owner is None: # Wait first call to compute it
                from useraccount import UserAccount
                self._owner = UserAccount(JID(node=self.account))
            return self._owner
        else:
            return BCAddress.__getattr__(self, name)

    def getPercentageReceived(self):
        '''Returns the percentage of bitcoins received on this address over the total received
           by the same user. If nothing was received yet, return None.'''
        total = self.owner.getTotalReceived()
        if 0 != total:
            return self.getReceived() * 100 / total
        else:
            return None

    def discoReceived(self, user, what, node):
        if 'info' == what:
            if node is None:
                ids = [{'category': 'hierarchy', 'type': 'branch', 'name': self.address}]
                return {'ids': ids, 'features': [NS_DISCO_INFO, NS_DISCO_ITEMS, NS_VERSION]}
        elif 'items' == what:
            items = []
            if node is None and ((user.jid == self.owner.jid) or (user.isAdmin())):
                items.append({'jid': self.owner.getLocalJID(), 'name': _(DISCO, 'address_owner')})
            return items

    def iqReceived(self, cnx, iq):
        queries = iq.getChildren() # there should be only one
        if 0 == len(queries):
            return
        ns = queries[0].getNamespace()
        typ = iq.getType()
        if NS_VCARD == ns and ('get' == typ):
            reply = iq.buildReply('result')
            query = reply.getQuery()
            query.addChild('FN', payload=[self.address])
            #TODO: More generic URL generation
            query.addChild('URL', payload=[_(DEFAULT, 'url_bitcoin_address').format(address=self.address)])
            cnx.send(reply)
            raise NodeProcessed
        Addressable.iqReceived(self, cnx, iq)

    def messageReceived(self, cnx, msg):
        from command import parse as parseCommand, Command
        from useraccount import UserAccount
        (action, args) = parseCommand(msg.getBody())
        command = Command(action, args, self)
        msg = msg.buildReply(command.execute(UserAccount(msg.getFrom())))
        msg.setType('chat')
        cnx.send(msg)
        raise NodeProcessed

    def presenceReceived(self, cnx, prs):
        from useraccount import UserAccount
        user = UserAccount(prs.getFrom())
        to = prs.getTo().getStripped()
        typ = prs.getType()
        if typ == 'subscribe':
            cnx.send(Presence(typ='subscribed', frm=to, to=user.jid))
            self.sendBitcoinPresence(cnx, user)
        elif typ == 'unsubscribe':
            cnx.send(Presence(typ='unsubscribed', frm=to, to=user.jid))
        elif typ == 'probe':
            self.sendBitcoinPresence(cnx, user)
        raise NodeProcessed

    def sendBitcoinPresence(self, cnx, user):
        '''Send a presence information to the user, from this address.'''
        if not user.isRegistered():
            return
        if user.ownsAddress(self):
            status = _(ROSTER, 'own_address')
            percentage = self.getPercentageReceived()
            if percentage is not None:
                status += '\n' + _(ROSTER, 'percentage_balance_received').format(percent=percentage)
        else:
            status = None
        cnx.send(Presence(to=user.jid, typ='available', show='online', status=status, frm=self.jid))


class CommandSyntaxError(Exception):
    '''There was a syntax in the command.'''
    pass
