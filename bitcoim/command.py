# vim: set fileencoding=utf-8 :

'''This module contains everything that is related to commands.
'''

from bitcoin.transaction import CATEGORY_MOVE, CATEGORY_SEND
from i18n import _, COMMANDS, TX
from jid import JID
from logging import debug, info
from paymentorder import PaymentOrder, PaymentError, PaymentNotFoundError, \
                         NotEnoughBitcoinsError, PaymentToSelfError
from useraccount import UserAccount

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
        for action in ['pay', 'history', 'cancel', 'confirm', 'help']:
            if _(COMMANDS, 'command_'+action) == self.action:
                return _(COMMANDS, 'command_'+action+'_usage')
        raise UnknownCommandError, self.action

    def expandAction(self):
        '''Try to guess the action from its first letters. If a match is found,
           replace self.action. Raise AmbiguousCommandError if more than one
           match is found. If there's no match, don't change anything.'''
        matches = []
        for a in ['pay', 'history', 'cancel', 'confirm', 'help']:
            command = _(COMMANDS, 'command_'+a)
            if 0 == command.find(self.action):
                matches.append(command)
        if 0 == len(matches):
            return
        if 1 == len(matches):
            self.action = matches[0]
            return
        raise AmbiguousCommandError(self.action, matches)

    def execute(self, user):
        """Actually execute the command, on behalf of the given user."""
        debug("A command was sent: %s" % self.action)
        self.expandAction()
        if _(COMMANDS, 'command_pay') == self.action:
            if self.target is None:
                raise CommandTargetError, _(TX, 'error_payment_to_gateway')
            try:
                amount = self.arguments.pop(0)
            except IndexError:
                raise CommandSyntaxError, _(TX, 'error_no_amount')
            comment = ' '.join(self.arguments)
            return self._executePay(user, amount, self.target, comment)
        elif _(COMMANDS, 'command_cancel') == self.action:
            try:
                code = self.arguments.pop(0)
                return self._executeCancel(user, code)
            except IndexError:
                return self._executeListPending(user)
        elif _(COMMANDS, 'command_confirm') == self.action:
            try:
                code = self.arguments.pop(0)
                return self._executeConfirm(user, code)
            except IndexError:
                return self._executeListPending(user)
        elif _(COMMANDS, 'command_help') == self.action:
            try:
                targetCommand = self.arguments.pop(0)
            except IndexError:
                targetCommand = None
            return self._executeHelp(user, self.target, targetCommand)
        elif _(COMMANDS, 'command_history') == self.action:
            return self._executeHistory(user)
        else:
            raise UnknownCommandError, self.action

    def _executePay(self, sender, amount, target, comment=''):
        """Called internally. Actually place the payment order in the pending
           list and generate the reply."""
        debug("Pay order (BTC %s to %s from %s, %s)" % (amount, target, sender, comment))
        try:
            amount = int(amount)
        except ValueError:
            raise CommandSyntaxError, _(TX, 'error_amount_non_number')
        if amount <= 0:
            raise CommandSyntaxError, _(TX, 'error_amount_non_positive')
        try:
            order = PaymentOrder(sender, target, amount, comment)
        except PaymentToSelfError:
            raise CommandSyntaxError, _(TX, 'error_payment_to_self')
        order.queue()
        info("Payment order valid, queued: %s -> %s (BTC %s, %s)" % \
             (sender, target, amount, order.code))
        if 0 == len(comment):
            reply = _(TX, 'confirm_recap').format(amount=amount, recipient=order.recipient)
        else:
            reply = _(TX, 'confirm_recap_comment').format(amount=amount, recipient=order.recipient, comment=comment)
        reply += ' ' + _(COMMANDS, 'confirm_prompt').format(code=order.code)
        if sender.getBalance() - amount < WARNING_LIMIT:
            reply += ' ' + _(TX, 'warning_low_balance').format(amount=sender.getBalance())
        return reply

    def _executeHistory(self, user):
        """Called internally. List the past transactions related to the user."""
        reply = ''
        for payment in user.pastPayments():
            if self.target is not None and (self.target.jid != payment.otheraccount):
                continue
            amount = payment.amount
            reply += "\n"
            if payment.otheraccount is None:
                reply += _(TX, 'history_recap_item').format(amount=amount)
            else:
                other = UserAccount(JID(payment.otheraccount))
                if other == self.target:
                    reply += _(TX, 'history_recap_item').format(amount=amount)
                else:
                    tofrom = 'to' if amount < 0 else 'from'
                    reply += _(TX, 'history_recap_item_%s' % tofrom).format(amount=abs(amount), dest=other.username)
            if payment.message is not None:
                reply = _(TX, 'tx_comment').format(message=reply, comment=payment.message)
            confirmations = payment.confirmations
            if 0 <= confirmations:
                reply = _(TX, 'tx_confirmations').format(message=reply, confirmations=payment.confirmations)
        if 0 == len(reply):
            if self.target is None:
                reply = _(TX, 'history_recap_nothing_global')
            else:
                reply = _(TX, 'history_recap_nothing_target')
        else:
            if self.target is None:
                reply = _(TX, 'history_recap_global').format(summary=reply)
            else:
                reply = _(TX, 'history_recap_target').format(summary=reply)
        return reply

    def _executeCancel(self, user, code=None):
        """Called internally. Do the cancellation of a pending payment order
           and generate the reply."""
        debug("Cancellation attempt from %s (%s)" % (user, code))
        try:
            payment = PaymentOrder(user, code=code)
        except PaymentNotFoundError:
            raise CommandError, _(TX, 'error_tx_not_found').format(code=code)
        payment.cancel()
        debug("Payment %s (BTC %s to %s) was cancelled by %s" % \
              (code, payment.amount, payment.recipient, user))
        target = self.target
        if target == payment.target:
            if 0 == len(payment.comment):
                reply = _(TX, 'cancel_recap_target').format(amount=payment.amount)
            else:
                reply = _(TX, 'cancel_recap_target_comment').format(amount=payment.amount, comment=payment.comment)
        else:
            if 0 == len(payment.comment):
                reply = _(TX, 'cancel_recap_other').format(amount=payment.amount, recipient=payment.recipient)
            else:
                reply = _(TX, 'cancel_recap_other_comment').format(amount=payment.amount, recipient=payment.recipient, comment=payment.comment)
            if target is None:
                reply += ' ' + _(TX, 'cancel_recap_warning_global')
            else:
                reply += ' ' + _(TX, 'cancel_recap_warning_other')
        return reply

    def _executeConfirm(self, user, code=None):
        """Called internally. Do the actual confirmation of a given payment
           order and generate the reply."""
        debug("Confirmation attempt from %s (%s)" % (user, code))
        try:
            payment = PaymentOrder(user, code=code)
        except PaymentNotFoundError:
            raise CommandError, _(TX, 'error_tx_not_found').format(code=code)
        try:
            transactionId = payment.confirm()
        except NotEnoughBitcoinsError:
            raise CommandError, _(TX, 'error_insufficient_funds')
        except PaymentError, message:
            raise CommandError, _(TX, 'error_payment_impossible').format(reason=message)
        info("BTC %s paid from %s to %s. Transaction ID: %s" % \
              (payment.amount, user, payment.recipient, transactionId))
        if 0 == transactionId:
            reply = _(TX, 'pay_recap_user')
        else:
            reply = _(TX, 'pay_recap').format(txid=transactionId)
        return reply

    def _executeListPending(self, user):
        """Called internally. Generate the listing of all pending payments."""
        reply = ''
        if self.target is None:
            label = _(TX, 'pending_header_global')
            empty = _(TX, 'pending_nothing_global')
            for row in user.pendingPayments():
                reply += "\n" + _(TX, 'pending_item_global').format(code=row['confirmation_code'],\
                                                                    date=row['date'].date().isoformat(),\
                                                                    amount=row['amount'],\
                                                                    recipient=row['recipient'])
                if 0 != len(row['comment']):
                    reply = _(TX, 'tx_comment').format(message=reply, comment=row['comment'])
        else:
            label = _(TX, 'pending_header_target')
            empty = _(TX, 'pending_nothing_target')
            for row in user.pendingPayments(self.target):
                reply += "\n" + _(TX, 'pending_item_target').format(code=row['confirmation_code'],\
                                                                    date=row['date'].date().isoformat(),\
                                                                    amount=row['amount'])
                if 0 != len(row['comment']):
                    reply = _(TX, 'tx_comment').format(message=reply, comment=row['comment'])
        if 0 == len(reply):
            return empty
        else:
            return label + reply

    def _executeHelp(self, user, target, command=None):
        """Called internally. Generate the help message for the given command,
           or the generic help message if no command was given."""
        if command is None:
            possibleCommands = [_(COMMANDS, 'command_help'), _(COMMANDS, 'command_history')]
            if (target is not None) and (target.jid != user.jid):
                possibleCommands.extend([_(COMMANDS, 'command_pay'), _(COMMANDS, 'command_confirm'), _(COMMANDS, 'command_cancel')])
            elif (target is None):
                possibleCommands.extend([_(COMMANDS, 'command_confirm'), _(COMMANDS, 'command_cancel')])
            reply = _(COMMANDS, 'command_list_prompt').format(lst=', '.join(possibleCommands))
            if target is None:
                reply += ' ' + _(COMMANDS, 'command_list_prompt_address')
        else:
            try:
                reply = _(COMMANDS, 'usage_message').format(usage=Command(command).usage())
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

class AmbiguousCommandError(CommandSyntaxError):
    '''The given command doesn't expand to a regular command'''
