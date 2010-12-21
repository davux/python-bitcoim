# vim: set fileencoding=utf-8 :

'''This module contains everything that is related to commands.
'''

from bitcoin.transaction import CATEGORY_MOVE, CATEGORY_SEND
from jid import JID
from logging import debug, info
from paymentorder import PaymentOrder, PaymentError, PaymentNotFoundError, \
                         NotEnoughBitcoinsError, PaymentToSelfError
from useraccount import UserAccount

COMMAND_HELP = 'help'
COMMAND_PAY = 'pay'
COMMAND_CANCEL = 'cancel'
COMMAND_CONFIRM = 'confirm'
COMMAND_PAID = 'paid'

WARNING_LIMIT = 10
'''The amount above which you will be warned when inserting a payment order'''

def parse(line):
    '''Parse a command line and return a tuple (action, arguments), where
       action is a word, and arguments is an array of words.
       If the line is empty, None is returned.'''
    parts = line.split(None, 1)
    if 0 == len(parts):
        return None
    action = parts.pop(0)
    try:
        arguments = parts[0].split()
    except IndexError:
        arguments = []
    return (action, arguments)


class Command(object):
    '''A command that is sent to the component.'''

    def __init__(self, action, arguments=[], target=None):
        '''Constructor. action is the command to perform. arguments is an
           array of words or phrases, target is the Addressable object the
           command is targetted at.'''
        self.action = action.lower()
        self.arguments = arguments
        self.target = target

    def usage(self):
        """Return an explanation message about how to use the command. Raise an
           exception if the command doesn't exist."""
        if COMMAND_PAY == self.action:
            return 'pay <amount> [<reason>]\n - <amount> must be a positive number\n - <reason> is a free-form text'
        if COMMAND_PAID == self.action:
            return 'paid\nList past payments'
        if COMMAND_CANCEL == self.action:
            return 'cancel [<code>]\n - <code> is the confirmation code of a pending payment\nIf no code is given, list all pending payments'
        if COMMAND_CONFIRM == self.action:
            return 'confirm [<code>]\n - <code> is the confirmation code of a pending payment\nIf no code is given, list all pending payments'
        elif COMMAND_HELP == self.action:
            return 'help [<command>]'
        else:
            raise UnknownCommandError, self.action

    def execute(self, user):
        """Actually execute the command, on behalf of the given user."""
        debug("A command was sent: %s" % self.action)
        if COMMAND_PAY == self.action:
            if self.target is None:
                raise CommandTargetError, 'You can only send coins to a user or an address.'
            try:
                amount = self.arguments.pop(0)
            except IndexError:
                raise CommandSyntaxError, 'You must specify an amount.'
            comment = ' '.join(self.arguments)
            return self._executePay(user, amount, self.target, comment)
        elif COMMAND_CANCEL == self.action:
            try:
                code = self.arguments.pop(0)
                return self._executeCancel(user, code)
            except IndexError:
                return self._executeListPending(user)
        elif COMMAND_CONFIRM == self.action:
            try:
                code = self.arguments.pop(0)
                return self._executeConfirm(user, code)
            except IndexError:
                return self._executeListPending(user)
        elif COMMAND_HELP == self.action:
            try:
                targetCommand = self.arguments.pop(0)
            except IndexError:
                targetCommand = None
            return self._executeHelp(user, self.target, targetCommand)
        elif COMMAND_PAID == self.action:
            return self._executePaid(user)
        else:
            raise UnknownCommandError, self.action

    def _executePay(self, sender, amount, target, comment=''):
        """Called internally. Actually place the payment order in the pending
           list and generate the reply."""
        debug("Pay order (BTC %s to %s from %s, %s)" % (amount, target, sender, comment))
        try:
            amount = int(amount)
        except ValueError:
            raise CommandSyntaxError, 'The amount must be a number.'
        if amount <= 0:
            raise CommandSyntaxError, 'The amount must be positive.'
        try:
            order = PaymentOrder(sender, target, amount, comment)
        except PaymentToSelfError:
            raise CommandSyntaxError, 'You know, I\'m your own address. It doesn\'t make sense.'
        order.queue()
        info("Payment order valid, queued: %s -> %s (BTC %s, %s)" % \
             (sender, target, amount, order.code))
        reply = "You want to pay BTC %s to %s" % (amount, order.recipient)
        if 0 != len(comment):
            reply += ' (%s)' % comment
        reply += ". Please confirm by typing: 'confirm %s'." % order.code
        if sender.getBalance() - amount < WARNING_LIMIT:
            reply += " Note: you only have BTC %d left on your account right now." % sender.getBalance()
        return reply

    def _executePaid(self, user):
        """Called internally. List the past outgoing transactions made by the
           user. The command behaves the same whatever the target (for now)."""
        reply = ''
        for payment in user.pastPayments():
            if payment.category not in [CATEGORY_SEND, CATEGORY_MOVE]:
                continue
            if self.target is not None and (self.target.jid != payment.otheraccount):
                continue
            reply += "\nBTC %s" % abs(payment.amount)
            if payment.otheraccount is not None:
                recipient = UserAccount(JID(payment.otheraccount))
                if recipient != self.target:
                    if user.isAdmin() or (0 != len(recipient.username)):
                        reply += " to %s" % recipient.getLabel()
                    else:
                        reply += " to another user who became invisible since then"
            if payment.message is not None:
                reply += " (%s)" % payment.message
            confirmations = payment.confirmations
            if 0 <= confirmations:
                reply += " – %s confirmations" % payment.confirmations
        if 0 == len(reply):
            if self.target is None:
                reply = "You didn't send any coins"
            else:
                reply = "You didn't send me any coins"
        else:
            if self.target is None:
                reply = "You paid:%s" % reply
            else:
                reply = "You paid me:%s" % reply
        return reply

    def _executeCancel(self, user, code=None):
        """Called internally. Do the cancellation of a pending payment order
           and generate the reply."""
        debug("Cancellation attempt from %s (%s)" % (user, code))
        try:
            payment = PaymentOrder(user, code=code)
        except PaymentNotFoundError:
            raise CommandError, 'No payment was found with code \'%s\'' % code
        payment.cancel()
        debug("Payment %s (BTC %s to %s) was cancelled by %s" % \
              (code, payment.amount, payment.recipient, user))
        target = self.target
        if target == payment.target:
            reply = "Cancelled payment of BTC %s to me" % payment.amount
            if 0 != len(payment.comment):
                reply += " (%s)" % payment.comment
            reply += ". Too bad!"
        else:
            reply = "Cancelled payment of BTC %s to %s" % (payment.amount, payment.recipient)
            if 0 != len(payment.comment):
                reply += " (%s)" % payment.comment
            if target is None:
                reply += ". Warning: It's better to cancel a payment from its recipient."
            else:
                reply += ". Warning: The payment was not to me. Since you gave the right code I cancelled it anyway."
        return reply

    def _executeConfirm(self, user, code=None):
        """Called internally. Do the actual confirmation of a given payment
           order and generate the reply."""
        debug("Confirmation attempt from %s (%s)" % (user, code))
        try:
            payment = PaymentOrder(user, code=code)
        except PaymentNotFoundError:
            raise CommandError, 'No payment was found with code \'%s\'' % code
        try:
            transactionId = payment.confirm()
        except NotEnoughBitcoinsError:
            raise CommandError, 'You don\'t have enough bitcoins to do that payment.'
        except PaymentError, message:
            raise CommandError, 'Can\'t confirm: %s' % message
        info("BTC %s paid from %s to %s. Transaction ID: %s" % \
              (payment.amount, user, payment.recipient, transactionId))
        if 0 == transactionId:
            reply = "Payment to another user done. This has an immediate effect."
        else:
            reply = "Payment done. Transaction ID: %s" % transactionId
        return reply

    def _executeListPending(self, user):
        """Called internally. Generate the listing of all pending payments."""
        reply = ''
        if self.target is None:
            label = "Pending payments:"
            empty = "No pending payments."
            for row in user.pendingPayments():
                reply += "\n[%s] (%s): BTC %s to %s" % (row['confirmation_code'], row['date'].date().isoformat(), row['amount'], row['recipient'])
                if 0 != len(row['comment']):
                    reply += ' (%s)' % row['comment']
        else:
            label = "Pending payments to me:"
            empty = "No pending payments to me."
            for row in user.pendingPayments(self.target):
                reply += "\n[%s] (%s): BTC %s" % (row['confirmation_code'], row['date'].date().isoformat(), row['amount'])
                if 0 != len(row['comment']):
                    reply += ' (%s)' % row['comment']
        if 0 == len(reply):
            return empty
        else:
            return label + reply

    def _executeHelp(self, user, target, command=None):
        """Called internally. Generate the help message for the given command,
           or the generic help message if no command was given."""
        if command is None:
            possibleCommands = ['help', 'paid']
            if (target is not None) and (target.account != user.jid):
                possibleCommands.extend(['pay', 'confirm', 'cancel'])
            elif (target is None):
                possibleCommands.extend(['confirm', 'cancel'])
            reply = 'Possible commands: %s. Type \'help <command>\' for details.' % ', '.join(possibleCommands)
            if target is None:
                reply += ' You can also type a bitcoin address directly to start a chat.'
        else:
            try:
                reply = "Usage: " + Command(command).usage()
            except UnknownCommandError:
                raise CommandSyntaxError, 'help: No such command \'%s\'' % command
        return reply


class CommandError(Exception):
    '''Generic error in command.'''

class CommandSyntaxError(CommandError):
    '''There was a syntax in the command.'''

class UnknownCommandError(CommandSyntaxError):
    '''Unknown command.'''

class CommandTargetError(CommandError):
    '''The target of the command is wrong (address instead of gateway or
       viceversa).'''
