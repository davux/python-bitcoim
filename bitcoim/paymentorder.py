from bitcoin.address import Address
from bitcoin.controller import Controller
from logging import debug, info, warning
from datetime import datetime
from db import SQL
from jsonrpc.proxy import JSONRPCException
from xmpp import JID
import random

class PaymentOrder(object):
    '''A payment order.'''

    def __init__(self, sender, address=None, username='', amount=None, comment='', fee=0, code=None):
        self.sender = sender
        self.recipient = None
        if (address is not None) and (0 != len(username)):
            raise InvalidPaymentError, 'You cannot give an address and a username'
        if address is not None:
            if sender.ownsAddress(address):
                raise PaymentToSelfError
            self.recipient = address.address
        elif 0 != len(username):
            if sender.username == username:
                raise PaymentToSelfError
            self.recipient = username
        if code is None:
            if (address is None) and (0 == len(username)):
                raise InvalidPaymentError, 'An address or a username must be given'
            self.amount = amount
            self.comment = comment
            self.fee = fee
            self.date = None
            self.entryId = None
        else:
            debug("We want to fetch payment with code '%s'" % code)
            self.code = code
            condition = 'from_jid=? and confirmation_code=?'
            values = [sender.jid, code]
            if self.recipient is not None:
                condition += ' and recipient=?'
                values.append(self.recipient)
            if amount is not None:
                condition += ' and amount=?'
                values.append(amount)
            if comment != '':
                condition += ' and comment=?'
                values.append(comment)
            if fee != 0:
                condition += ' and fee=?'
                values.append(fee)
            req = 'select %s, %s, %s, %s, %s, %s from %s where %s' % \
                  ('id', 'date', 'recipient', 'amount', 'comment', 'fee', \
                   'payments', condition)
            debug("SQL query: %s" % req)
            SQL().execute(req, tuple(values))
            paymentOrder = SQL().fetchone()
            if paymentOrder is None:
                raise PaymentNotFoundError
            else:
                (self.entryId, self.date, self.recipient, self.amount, \
                 self.comment, self.fee) = tuple(paymentOrder)

    @staticmethod
    def genConfirmationCode(length=4, alphabet='abcdefghjkmnpqrstuvwxyz23456789'):
        '''Generate a random confirmation code of variable length, taken from a
           given set of characters. By default, the length is 6 and the possible
           characters are lowercase letters (except o, i and l to avoid confusion)
           and numbers (except 0 and 1, for the same reason).
        '''
        debug("Trying to pick a %s-char word out of %s" % (length, alphabet))
        return ''.join(random.sample(alphabet, length)) 

    def queue(self):
        '''Insert a payment order into the database.'''
        self.code = PaymentOrder.genConfirmationCode()
        self.date = datetime.now()
        req = 'insert into %s (%s, %s, %s, %s, %s, %s, %s) values (?, ?, ?, ?, ?, ?, ?)' % \
              ('payments', 'from_jid', 'date', 'recipient', 'amount', 'comment', 'confirmation_code', 'fee')
        SQL().execute(req, (self.sender.jid, self.date, self.recipient, self.amount, self.comment, self.code, self.fee))
        self.entryId = SQL().lastrowid
        debug("Inserted a payment into database (id = %s)" % self.entryId)

    def confirm(self):
        '''Actually send the bitcoins to the recipient. Check first if the
           user has enough bitcoins to do the payment.
           If the recipient is a username, the corresponding bitcoin account
           is resolved, and the coins are simply moved to that account.
        '''
        from useraccount import UserAccount
        info("User %s is about to send BTC %s to %s" % (self.sender, self.amount, self.recipient))
        try:
            if Controller().validateaddress(self.recipient)['isvalid']:
                self.code = Controller().sendfrom(self.sender.jid,
                              self.recipient, self.amount, 1, self.comment)
            else:
                # If there's an UnknownUserError, let it go up one level
                destAccount = UserAccount(self.recipient).jid
                debug("We resolved %s into account '%s'" % (self.recipient, destAccount))
                Controller().move(self.sender.jid, destAccount, self.amount, 1, self.comment)
                self.code = 0
        except JSONRPCException, inst:
            info("Couldn't do payment, probably not enough bitcoins (%s)" % inst)
            raise NotEnoughBitcoinsError
        info("Payment made by %s to %s (BTC %s). Comment: %s" % \
              (self.sender, self.recipient, self.amount, self.comment))
        self.date = datetime.now()
        debug("About to delete payment order #%s" % self.entryId)
        req = 'delete from %s where %s=?' % ('payments', 'id')
        SQL().execute(req, (self.entryId,))
        return self.code

class PaymentNotFoundError(Exception):
    '''The requested payment was not found.'''

class PaymentError(Exception):
    '''The payment could not be made'''

class NotEnoughBitcoinsError(PaymentError):
    '''The user doesn't have enough bitcoins on their account'''

class PaymentToSelfError(PaymentError):
    '''The sender and the destination address represent the same account'''
