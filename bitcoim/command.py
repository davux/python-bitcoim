from logging import debug, info
from paymentorder import PaymentOrder, PaymentError, PaymentNotFoundError, \
                         NotEnoughBitcoinsError, PaymentToSelfError

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

    def __init__(self, action, arguments=[], target=None, username=''):
        '''Constructor. action is the action to perform. arguments is an array
           of words, target is the involved Address if any, and username is
           the involved username if any.
        '''
        self.action = action.lower()
        self.arguments = arguments
        self.target = target
        self.username = username

    def usage(self):
        if COMMAND_PAY == self.action:
            return 'pay <amount> [<reason>]\n - <amount> must be a positive number\n - <reason> is a free-form text'
        if COMMAND_CONFIRM == self.action:
            return 'confirm [<code>]\n - <code> is the confirmation code of a pending payment\nIf no code is given, list all pending payments'
        elif COMMAND_HELP == self.action:
            return 'help [<command>]'
        else:
            raise UnknownCommandError, self.action

    def execute(self, user):
        debug("A command was sent: %s" % self.action)
        if COMMAND_PAY == self.action:
            if (self.target is None) and (0 == len(self.username)):
                raise CommandTargetError, 'You can only send coins to a user or an address.'
            try:
                amount = self.arguments.pop(0)
            except IndexError:
                raise CommandSyntaxError, 'You must specify an amount.'
            comment = ' '.join(self.arguments)
            return self._executePay(user, amount, self.target, self.username, comment)
        elif COMMAND_CONFIRM == self.action:
            try:
                code = self.arguments.pop(0)
                return self._executeConfirm(user, code)
            except IndexError:
                return self._executeConfirmList(user)
        elif COMMAND_HELP == self.action:
            try:
                targetCommand = self.arguments.pop(0)
            except IndexError:
                targetCommand = None
            return self._executeHelp(user, self.target, targetCommand)
        else:
            raise UnknownCommandError, self.action

    def _executePay(self, sender, amount, address, username, comment=''):
        debug("Pay order (BTC %s to %s from %s, %s)" % (amount, address, sender, comment))
        try:
            amount = int(amount)
        except ValueError:
            raise CommandSyntaxError, 'The amount must be a number.'
        if amount <= 0:
            raise CommandSyntaxError, 'The amount must be positive.'
        try:
            order = PaymentOrder(sender, address, username, amount, comment)
        except PaymentToSelfError:
            raise CommandSyntaxError, 'You know, I\'m your own address. It doesn\'t make sense.'
        order.queue()
        info("Payment order valid, queued: %s -> %s/%s (BTC %s, %s)" % \
             (sender, address, username, amount, order.code))
        reply = "You want to pay BTC %s to %s" % (amount, order.recipient)
        if 0 != len(comment):
            reply += ' (%s)' % comment
        reply += ". Please confirm by typing: 'confirm %s'." % order.code
        if sender.getBalance() - amount < WARNING_LIMIT:
            reply += " Note: you only have BTC %d left on your account right now." % sender.getBalance()
        return reply

    def _executeConfirm(self, user, code=None):
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

    def _executeConfirmList(self, user):
        reply = ''
        if self.target is None:
            label = "Pending payments:"
            empty = "No pending payments."
            for row in user.pendingPayments():
                reply += "\n[%s] (%s): BTC %s to %s" % (row['confirmation_code'], row['date'].date().isoformat(), row['amount'], row['recipient'])
                if 0 != len(row['comment']):
                    reply += ' (%s)' % row['comment']
        else:
            label = "Pending payments to this address:"
            empty = "No pending payments to this address."
            for row in user.pendingPayments(self.target.address):
                reply += "\n[%s] (%s): BTC %s" % (row['confirmation_code'], row['date'].date().isoformat(), row['amount'])
                if 0 != len(row['comment']):
                    reply += ' (%s)' % row['comment']
        if 0 == len(reply):
            return empty
        else:
            return label + reply

    def _executeHelp(self, user, target, command=None):
        if command is None:
            possibleCommands = ['help']
            if (target is not None) and (target.account != user.jid):
                possibleCommands.extend(['pay', 'confirm'])
            elif (target is None):
                possibleCommands.extend(['confirm'])
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
