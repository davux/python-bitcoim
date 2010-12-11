from logging import debug, info
from paymentorder import PaymentOrder, PaymentError, PaymentNotFoundError, \
                         NotEnoughBitcoinsError

COMMAND_HELP = 'help'
COMMAND_PAY = 'pay'
COMMAND_CONFIRM = 'confirm'

WARNING_LIMIT = 10

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
        '''Constructor. action is the action to perform. arguments is an array
           of words, target is either an Address or None if it's the gateway
           itself.'''
        self.action = action.lower()
        self.arguments = arguments
        self.target = target

    def usage(self):
        if COMMAND_PAY == self.action:
            return 'pay <amount> [<reason>]\n - <amount> must be a positive number\n - <reason> is a free-form text'
        if COMMAND_CONFIRM == self.action:
            return 'confirm <code>\n - <code> is the confirmation code of a pending payment'
        elif COMMAND_HELP == self.action:
            return 'help [<command>]'
        else:
            raise UnknownCommandError

    def execute(self, user):
        debug("A command was sent: %s" % self.action)
        if COMMAND_PAY == self.action:
            if self.target is None:
                raise CommandTargetError
            try:
                amount = self.arguments.pop(0)
            except IndexError:
                raise CommandSyntaxError, 'You must specify an amount.'
            comment = ' '.join(self.arguments)
            return self._executePay(user, amount, self.target, comment)
        elif COMMAND_CONFIRM == self.action:
            try:
                code = self.arguments.pop(0)
            except IndexError:
                raise CommandSyntaxError, 'You must give a confirmation code.'
            return self._executeConfirm(user, code)
        elif COMMAND_HELP == self.action:
            try:
                targetCommand = self.arguments.pop(0)
            except IndexError:
                targetCommand = None
            return self._executeHelp(self.target, targetCommand)
        else:
            raise UnknownCommandError

    def _executePay(self, sender, amount, address, comment=''):
        debug("Pay order (BTC %s to %s from %s, %s)" % (amount, address, sender, comment))
        try:
            amount = int(amount)
        except ValueError:
            raise CommandSyntaxError, 'The amount must be a number.'
        if amount <= 0:
            raise CommandSyntaxError, 'The amount must be positive.'
        order = PaymentOrder(sender, address, amount, comment)
        order.queue()
        info("Payment order valid, queued: %s -> %s (BTC %s, %s)" % \
             (sender, address, amount, order.code))
        reply = "You want to pay BTC %s to address %s" % (amount, order.address)
        if 0 != len(comment):
            reply += ' (%s)' % comment
        reply += ". Please confirm by typing: 'confirm %s'." % order.code
        if sender.getBalance() - amount < WARNING_LIMIT:
            reply += " Note: you only have BTC %d left on your account right now." % sender.getBalance()
        return reply

    def _executeConfirm(self, user, code):
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
              (payment.amount, user, payment.address, transactionId))
        reply = "Payment done. Transaction ID: %s" % transactionId
        return reply

    def _executeHelp(self, target, command=None):
        if command is None:
            if target is None:
                reply = 'Possible commands: help. Type \'help <command>\' for details. You can also type a bitcoin address directly to start a chat.'
            else:
                reply = 'Possible commands: pay, confirm, help. Type \'help <command>\' for details.'
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
