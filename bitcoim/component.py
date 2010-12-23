# -*- coding: utf-8 -*-
# vi: sts=4 et sw=4

from address import Address
from addressable import Addressable, generate as generateAddressable
from bitcoim import LIB_NAME, LIB_DESCRIPTION, LIB_VERSION
from bitcoin.address import InvalidBitcoinAddressError
from bitcoin.controller import Controller
from command import Command, parse as parseCommand, COMMAND_HELP, \
                    CommandSyntaxError, CommandTargetError, CommandError, \
                    UnknownCommandError
from datetime import datetime
from i18n import _, COMMANDS, DISCO, ROSTER
from jid import JID
from logging import debug, info, warning
from useraccount import UserAccount, AlreadyRegisteredError, UnknownUserError,\
                        UsernameNotAvailableError
from xmpp.browser import Browser
from xmpp.client import Component as XMPPComponent
from xmpp.jep0106 import JIDDecode
from xmpp.protocol import Message, Iq, Presence, NodeProcessed, \
                          Error, ErrorNode, \
                          NS_IQ, NS_MESSAGE, NS_PRESENCE, NS_DISCO_INFO, \
                          NS_DISCO_ITEMS, NS_GATEWAY, NS_REGISTER, \
                          NS_NICK, NS_VERSION, NS_LAST, NS_VCARD
from xmpp.simplexml import Node

class Component(Addressable, XMPPComponent):
    '''The component itself.'''

    def __init__(self, jid, password, server, port=5347, debuglevel=[]):
        '''Constructor.
           - Establish a session
           - Declare handlers
           - Send initial presence probe to all users
           - Send initial presence broadcasts to all users, from the gateway
             and from each of their "contacts" (bitcoin addresses)
        '''
        JID.domain = jid
        self.last = datetime.now()
        self.jid = jid
        self.password = password
        self.connectedUsers = set()
        XMPPComponent.__init__(self, server, port, debug=debuglevel, \
                               domains=[jid])

    def start(self, proxy=None):
        if not self.connect(None, proxy):
            raise Exception(_('Console', 'cannot_connect').format(server=self.Server, port=self.Port))
        if not self.auth(self.jid, self.password):
            raise Exception(_('Console', 'cannot_auth').format(jid=self.jid))
        self._RegisterHandlers()
        debug("Sending initial presence to all contacts...")
        for jid in UserAccount.getAllContacts():
            self.send(Presence(to=jid, frm=self.jid, typ='probe'))
            user = UserAccount(JID(jid))
            self.sendBitcoinPresence(self, user)
            for addr in user.getRoster():
                Address(JID(addr)).sendBitcoinPresence(self, user)

    def _RegisterHandlers(self):
        '''Define the Service Discovery information for automatic handling
           by the xmpp library.
        '''
        self.RegisterHandler(NS_MESSAGE, self.messageHandler)
        self.RegisterHandler(NS_PRESENCE, self.presenceHandler)
        self.RegisterHandler(NS_IQ, self.iqHandler)
        browser = Browser()
        browser.PlugIn(self)
        browser.setDiscoHandler(self.discoHandler)

    def discoHandler(self, cnx, iq, what):
        '''Dispatcher for disco queries addressed to any JID hosted at the
           gateway, including the gateway itself. Calls discoReceived() on the
           user, the address or the gateway depending on the recipient.
           A note about querying users: You should normally query a user by
           their username, provided they set one. If you're an admin, you can
           additionally query them from their real JID, in any case.
        '''
        fromUser = UserAccount(iq.getFrom())
        target = generateAddressable(iq.getTo(), [self], fromUser)
        if target is not None:
            return target.discoReceived(fromUser, what, iq.getQuerynode())
        # otherwise the default handler will send a "not supported" error

    def iqHandler(self, cnx, iq):
        '''IQ received'''
        fromUser = UserAccount(iq.getFrom())
        target = generateAddressable(iq.getTo(), [self], fromUser)
        if target is not None:
            return target.iqReceived(cnx, iq)
        # otherwise the default handler will send a "not supported" error

    def messageHandler(self, cnx, msg):
        '''Message received'''
        fromUser = UserAccount(msg.getFrom())
        target = generateAddressable(msg.getTo(), [self], fromUser)
        if target is not None:
            try:
                return target.messageReceived(cnx, msg)
            except CommandTargetError, reason:
                error = reason
            except UnknownCommandError, command:
                error = (_(COMMANDS, 'unknown_command').format(command=command))
            except CommandSyntaxError, reason:
                error = reason
            except CommandError, reason:
                error = reason
            msg = msg.buildReply(_(COMMANDS, 'error_message').format(\
                                   message=error))
            msg.setType('error')
            cnx.send(msg)
            raise NodeProcessed
        # otherwise the default handler will send a "not supported" error

    def presenceHandler(self, cnx, prs):
        '''Presence received. If any presence stanza is received from an
           unregistered user, don't even look at it. They should register
           first.'''
        fromUser = UserAccount(prs.getFrom())
        if not fromUser.isRegistered():
            return #TODO: Send a registration-required error
        target = generateAddressable(prs.getTo(), [self], fromUser)
        if target is not None:
            return target.presenceReceived(cnx, prs)
        # otherwise the default handler will send a "not supported" error

    def sayGoodbye(self):
        '''Ending method. Doesn't do anything interesting yet.'''
        message = 'Service is shutting down. See you later.'
        for user in self.connectedUsers:
            self.send(Presence(to=user.jid, frm=self.jid, typ='unavailable', status=message))
            for addr in user.getRoster():
                self.send(Presence(to=user.jid, frm=addr, typ='unavailable', status=message))
        debug("Bye.")
        self.send('</stream:stream>')

    def sendBitcoinPresence(self, cnx, user):
        '''Send a presence information to the user, from the component.'''
        if not user.isRegistered():
            return
        username = user.username
        if 0 == len(username):
            status = ''
        else:
            status = _(ROSTER, 'hello_nick').format(nick=username)
        status += _(ROSTER, 'current_balance').format(amount=user.getBalance())
        self.send(Presence(to=user.jid, typ='available', show='online', status=status, frm=self.jid))

    def addAddressToRoster(self, address, user):
        '''Add the JID corresponding to a given bitcoin address to user's
           roster. The suggested name is the bitcoin address.'''
        debug("Adding address %s to %s's roster")
        msg = _(ROSTER, 'new_address_message')
        pres = Presence(typ='subscribe', status=msg, frm=address.jid, to=user.jid)
        pres.addChild('nick', payload=[address.address], namespace=NS_NICK)
        self.send(pres)

    def discoReceived(self, user, what, node):
        if 'info' == what:
            if node is None:
                ids = [{'category': 'gateway', 'type': 'bitcoin',
                        'name':LIB_DESCRIPTION}]
                return {'ids': ids, 'features': [NS_DISCO_INFO, NS_DISCO_ITEMS, NS_REGISTER, NS_VERSION, NS_GATEWAY, NS_LAST]}
            elif 'users' == node:
                ids = [{'category': 'directory', 'type': 'user', 'name': _(DISCO, 'user_list')}]
                return {'ids': ids, 'features': [NS_DISCO_INFO, NS_DISCO_ITEMS]}
        elif 'items' == what:
            items = []
            if user.isRegistered():
                if node is None:
                    items.append({'jid': user.getLocalJID(), 'name': _(DISCO, 'your_addresses'), 'node': 'addresses'})
            else:
                items.append({'jid': self.jid, 'name': LIB_DESCRIPTION})
            if user.isAdmin():
                if node is None:
                    items.append({'jid': self.jid, 'name': 'Users', 'node': 'users'})
                elif 'users' == node:
                    for jid in UserAccount.getAllContacts():
                        contact = UserAccount(JID(jid))
                        if 0 == len(contact.username):
                            name = contact.jid
                        else:
                            name = contact.username
                        items.append({'jid': contact.getLocalJID(), 'name': name})
            return items

    def messageReceived(self, cnx, msg):
        '''Message received, addressed to the component. The command execution
           can raise exceptions, but those will be taken care of by the
           caller (messageHandler())'''
        user = UserAccount(msg.getFrom())
        if user.isRegistered():
            try:
                address = Address(msg.getBody())
                msg = Message(to=msg.getFrom(), frm=address.jid,\
                      body=_(ROSTER, 'address_start_chat').format(address=address), typ='chat')
            except InvalidBitcoinAddressError:
                (action, args) = parseCommand(msg.getBody())
                msg = msg.buildReply(Command(action, args).execute(user))
                msg.setType('chat')
                if user.checkBalance() is not None:
                    self.sendBitcoinPresence(cnx, user)
        else:
            error = _(REGISTRATION, 'error_not_registered')
            msg = msg.buildReply(_(COMMANDS, 'error_message').format(message=error))
            msg.setType('error')
        cnx.send(msg)
        raise NodeProcessed

    def presenceReceived(self, cnx, prs):
        '''Presence received from a registered user'''
        frm = prs.getFrom()
        user = UserAccount(frm)
        resource = frm.getResource()
        to = prs.getTo().getStripped()
        typ = prs.getType()
        if typ == 'subscribe':
            cnx.send(Presence(typ='subscribed', frm=to, to=user.jid))
            self.sendBitcoinPresence(cnx, user)
        elif typ == 'subscribed':
            debug('We were allowed to see %s\'s presence.' % user)
        elif typ == 'unsubscribe':
            debug('Just received an "unsubscribe" presence stanza. What does that mean?')
        elif typ == 'unsubscribed':
            debug('Unsubscribed. Any interest in this information?')
        elif typ == 'probe':
            self.sendBitcoinPresence(cnx, user)
        elif (typ == 'available') or (typ is None):
            self.userResourceConnects(user, resource)
        elif typ == 'unavailable':
            self.userResourceDisconnects(user, resource)
        elif typ == 'error':
            debug('Presence error. TODO: Handle it by not sending presence updates to them until they send a non-error.')
        raise NodeProcessed

    def iqReceived(self, cnx, iq):
        '''IQ handler for the component'''
        typ = iq.getType()
        queries = iq.getChildren() # there should be only one
        if 0 == len(queries):
            return
        ns = queries[0].getNamespace()
        debug("OK we're handling IQ %s, ns=%s" % (typ, ns))
        if NS_REGISTER == ns:
            if 'set' == typ:
                children = iq.getQueryChildren()
                if (0 != len(children)) and ('remove' == children[0].getName()):
                    self.unregistrationRequested(iq)
                else:
                    self.registrationRequested(iq)
                raise NodeProcessed
            elif 'get' == typ:
                instructions = Node('instructions')
                username = Node('username')
                user = UserAccount(iq.getFrom())
                registered = user.isRegistered()
                if registered:
                    instructions.setData(_(REGISTRATION, 'set_username'))
                    username.setData(user.username)
                else:
                    debug("A new user is preparing a registration")
                    instructions.setData(_(REGISTRATION, 'instructions'))
                reply = iq.buildReply('result')
                query = reply.getQuery()
                if registered:
                    query.addChild('registered')
                query.addChild(node=instructions)
                query.addChild(node=username)
                cnx.send(reply)
                raise NodeProcessed
            else:
                # Unkown namespace and type. The default handler will take care of it if we don't raise NodeProcessed.
                debug("Unknown IQ with ns '%s' and type '%s'." % (ns, typ))
        elif NS_GATEWAY == ns:
            if 'get' == typ:
                reply = iq.buildReply('result')
                query = reply.getQuery()
                query.addChild('desc', payload=[_(ROSTER, 'address2jid_description')])
                query.addChild('prompt', payload=[_(ROSTER, 'address2jid_prompt')])
                cnx.send(reply)
                raise NodeProcessed
            elif 'set' == typ:
                children = iq.getQueryChildren()
                if (0 != len(children)) and ('prompt' == children[0].getName()):
                    prompt = children[0].getData()
                    debug("Someone wants to convert %s into a JID" % prompt)
                    jid = Node('jid')
                    try:
                        jid.setData(Address(prompt).jid)
                    except InvalidBitcoinAddressError:
                        try:
                            jid.setData(UserAccount(prompt).getLocalJID())
                        except UnknownUserError:
                            reply = iq.buildReply(typ='error')
                            reply.addChild(node=ErrorNode('item-not-found', 404, 'cancel', _(ROSTER, 'address2jid_invalid')))
                            cnx.send(reply)
                            raise NodeProcessed
                    reply = iq.buildReply('result')
                    query = reply.getQuery()
                    query.addChild(node=jid)
                    cnx.send(reply)
                    raise NodeProcessed
        elif NS_VCARD == ns:
            if 'get' == typ:
                reply = iq.buildReply('result')
                query = reply.getQuery()
                query.addChild('FN', payload=["%s v%s" % (LIB_NAME, LIB_VERSION)])
                query.addChild('DESC', payload=[LIB_DESCRIPTION])
                cnx.send(reply)
                raise NodeProcessed
        Addressable.iqReceived(self, cnx, iq)

    def userResourceConnects(self, user, resource):
        '''Called when the component receives a presence"available" from a
           user. This method first registers the resource. Then, if it's the
           user's first online resource: sends them a presence packet, and
           internally adds them to the list of online users.'''
        debug("New resource (%s) for user %s" % (resource, user))
        user.resourceConnects(resource)
        if not user in self.connectedUsers:
            self.sendBitcoinPresence(self, user)
            self.connectedUsers.add(user)
            for jid in user.getRoster():
                Address(JID(jid)).sendBitcoinPresence(self, user)

    def userResourceDisconnects(self, user, resource):
        '''Called when the component receives a presence "unavailable" from
           a user. This method first unregisters the resource. Then, if the
           user has no more online resource, sends them an "unavailable" presence,
           and internally removes them from the list of online users.'''
        debug("Resource %s of user %s went offline" % (resource, user))
        user.resourceDisconnects(resource)
        if (user in self.connectedUsers) and (0 == len(user.resources)):
            jid = JID(user.jid)
            jid.setResource(resource=resource)
            self.send(Presence(typ='unavailable', frm=self.jid, to=jid))
            self.connectedUsers.remove(user)
            for address in user.getRoster():
                self.send(Presence(typ='unavailable', frm=address, to=jid))

    def registrationRequested(self, iq):
        '''A registration request was received. If an invalid username is
           choosen, the whole registration fails (people don't have to pick
           one, though). Also, although it's normally impossible, we're being
           paranoid and forbid registrations from JIDs that don't contain a
           dot, since they might conflict with usernames.'''
        frm = iq.getFrom()
        info("Registration request from %s" % frm)
        if -1 == frm.getStripped().find('.'):
            reply = iq.buildReply(typ='error')
            reply.addChild(node=ErrorNode('not-acceptable', 500, 'cancel', _(REGISTRATION, 'error_invalid_jid')))
            self.send(reply)
            warning("Possible hacking attempt: JID '%s' (no dot!) tried to register to the gateway." % frm.getStripped())
            return
        isUpdate = False
        user = UserAccount(frm)
        requestedUsername = ''
        for child in iq.getQueryChildren():
            if 'username' == child.getName():
                requestedUsername = child.getData()
                break
        try:
            user.username = requestedUsername
            info("%s changed username to '%s'" % (user, user.username))
        except UsernameNotAvailableError:
            reply = iq.buildReply(typ='error')
            reply.addChild(node=ErrorNode('not-acceptable', 406, 'modify', _(REGISTRATION, 'error_invalid_username')))
            self.send(reply)
            return
        try:
            user.register()
            new_address = user.createAddress()
            self.addAddressToRoster(new_address, user)
        except AlreadyRegisteredError:
            info("(actually just an update)")
            isUpdate = True
        self.send(Iq(typ='result', to=frm, frm=self.jid, attrs={'id': iq.getID()}))
        if not isUpdate:
            self.send(Presence(typ='subscribe', to=frm.getStripped(), frm=self.jid))

    def unregistrationRequested(self, iq):
        '''An unregistration request was received'''
        user = UserAccount(iq.getFrom())
        info("Unegistration request from %s" % user)
        try:
            user.unregister()
        except UnknownUserError:
            pass # We don't really mind about unknown people wanting to unregister. Should we?
        self.send(iq.buildReply('result'))
        self.send(Presence(to=user.jid, frm=self.jid, typ='unsubscribe'))
        self.send(Presence(to=user.jid, frm=self.jid, typ='unsubscribed'))
        self.send(Presence(to=user.jid, frm=self.jid, typ='unavailable', status=_(REGISTRATION, 'bye')))
