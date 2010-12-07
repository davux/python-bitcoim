from bitcoin.address import Address as BCAddress
from paymentorder import PaymentOrder
from xmpp.protocol import JID

ENCODING_SEP = '-'
ENCODING_BASE = 36 # Any value from 2 to 36 would work - smaller values produce longer suffixes

class Address(BCAddress):
    '''A Bitcoin address, but with some xmpp-specific capabilities. In particular, it has
       a 'jid' attribute that represents is encoding as a JID. Reciprocally, it's possible
       to construct an address with a JID.
    '''

    domain = None

    def __new__(cls, address=None):
        if cls.domain is None:
            raise DomainNotConfiguredError
        return BCAddress.__new__(cls)

    def __init__(self, address=None):
        '''Constructor. Initialize a bitcoin address normally.
           If the argument is a JID object, though, decode it first.
        '''
        self._jid = None
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
                self._jid = JID(node=self.address.lower() + suffix, domain=Address.domain)
            return self._jid
        else:
            return BCAddress.__getattr__(self, name)

    def getPercentageReceived(self):
        '''Returns the percentage of bitcoins received on this address over the total received
           by the same user. If nothing was received yet, return None.'''
        from useraccount import UserAccount
        user = UserAccount(JID(self.account))
        total = user.getTotalReceived()
        if 0 != total:
            return self.getReceived() * 100 / total
        else:
            return None


class CommandSyntaxError(Exception):
    '''There was a syntax in the command.'''
    pass

class DomainNotConfiguredError(Exception):
    '''The addresses' JID cannot be determined because no domain was configured.'''
