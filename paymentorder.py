from bitcoin.controller import Controller
from common import debug
from datetime import datetime
from db import SQL
from xmpp import JID
import random

class PaymentOrder(object):
    '''A payment order.'''

    def __init__(self, from_jid, address=None, amount=None, comment='', fee=0, code=None):
        self.jid = from_jid
        if code is None:
            self.address = address
            self.amount = amount
            self.comment = comment
            self.fee = fee
            self.date = None
            self.paid = False
            self.entryId = None
        else:
            debug("We want to fetch payment with code '%s'" % code)
            self.code = code
            condition = 'from_jid=? and confirmation_code=?'
            values = [from_jid, code]
            if address is not None:
                condition += ' and recipient=?'
                values.append(address)
            if amount is not None:
                condition += ' and amount=?'
                values.append(amount)
            if comment != '':
                condition += ' and comment=?'
                values.append(comment)
            if fee != 0:
                condition += ' and fee=?'
                values.append(fee)
            req = 'select %s, %s, %s, %s, %s, %s, %s from %s where %s' % \
                  ('id', 'date', 'recipient', 'amount', 'comment', 'fee', \
                   'paid', 'payments', condition)
            debug("SQL query: %s" % req)
            SQL().execute(req, tuple(values))
            paymentOrder = SQL().fetchone()
            if paymentOrder is None:
                raise PaymentNotFoundError
            else:
                (self.entryId, self.date, self.address, self.amount, \
                 self.comment, self.fee, self.paid) = tuple(paymentOrder)

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
        SQL().execute(req, (self.jid, self.date, self.address, self.amount, self.comment, self.code, self.fee))
        self.entryId = SQL().lastrowid

    def confirm(self):
        '''Actually send the bitcoins to the recipient. Check first if the
           user has enough bitcoins to do the payment.'''
        from useraccount import UserAccount
        user = UserAccount(JID(self.jid))
        if user.lockPayments():
            if user.getBalance() >= self.amount:
                try:
                    self.code = Controller().sendtoaddress(self.address, \
                                  self.amount, self.comment)
                except jsonrpc.proxy.JSONRPCException:
                    raise PaymentError, 'Could not make payment (unknown reason).'
                user.unlockPayments()
            else:
              user.unlockPayments()
              raise NotEnoughBitcoinsError
        else:
            raise AccountLockedError
        debug("Payment made to by %s to %s (BTC %s). Comment: %s" % \
              (self.jid, self.address, self.amount, self.comment))
        self.date = datetime.now()
        self.paid = True
        req = 'update %s set %s=?, %s=?, %s=? where %s=?' % \
              ('payments', 'paid', 'date', 'confirmation_code', 'id')
        SQL().execute(req, (self.paid, self.date, self.code, self.entryId))
        return self.code

class PaymentNotFoundError(Exception):
    '''The requested payment was not found.'''

class PaymentError(Exception):
    '''The payment could not be made'''

class NotEnoughBitcoinsError(PaymentError):
    '''The user doesn't have enough bitcoins on their account'''

class AccountLockedError(PaymentError):
    '''The user's account is locked. Can't do any payments'''
