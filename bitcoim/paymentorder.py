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

    def __init__(self, sender, address=None, amount=None, comment='', fee=0, code=None):
        self.sender = sender
        if code is None:
            if sender.jid == address.account:
                raise PaymentToSelfError
            self.address = address
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
            if address is not None:
                condition += ' and recipient=?'
                values.append(address.address)
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
                (self.entryId, self.date, self.address, self.amount, \
                 self.comment, self.fee) = tuple(paymentOrder)
                self.address = Address(self.address)

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
        SQL().execute(req, (self.sender.jid, self.date, self.address.address, self.amount, self.comment, self.code, self.fee))
        self.entryId = SQL().lastrowid
        debug("Inserted a payment into database (id = %s)" % self.entryId)

    def confirm(self):
        '''Actually send the bitcoins to the recipient. Check first if the
           user has enough bitcoins to do the payment.
        '''
        info("User %s is about to send BTC %s to %s" % (self.sender, self.amount, self.address))
        try:
            self.code = Controller().sendfrom(self.sender.jid,
                          self.address.address, self.amount, 1, self.comment)
        except JSONRPCException, inst:
            info("Couldn't do payment, probably not enough bitcoins (%s)" % inst)
            raise NotEnoughBitcoinsError
        info("Payment made by %s to %s (BTC %s). Comment: %s" % \
              (self.sender, self.address, self.amount, self.comment))
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
