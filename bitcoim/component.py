# -*- coding: utf-8 -*-
# vi: sts=4 et sw=4

from bitcoim.address import Address
from bitcoim.command import Command, parse as parseCommand, COMMAND_HELP, \
                            CommandSyntaxError, CommandTargetError, \
                            CommandError, UnknownCommandError

from bitcoin.address import InvalidBitcoinAddressError
from bitcoin.controller import Controller
from datetime import datetime
from logging import debug, info, warning
from useraccount import UserAccount, AlreadyRegisteredError, \
                        UsernameNotAvailableError, UnknownUserError
from xmpp.client import Component as XMPPComponent
from xmpp.jep0106 import JIDDecode
from xmpp.protocol import JID, Message, Iq, Presence, NodeProcessed, \
                          Error, ErrorNode, \
                          NS_IQ, NS_MESSAGE, NS_PRESENCE, NS_DISCO_INFO, \
                          NS_DISCO_ITEMS, NS_GATEWAY, NS_REGISTER, \
                          NS_VERSION, NS_LAST
from protocol import NS_NICK
from xmpp.simplexml import Node
from xmpp.browser import Browser

APP_NAME = 'BitcoIM'
APP_IDENTIFIER = 'bitcoim'
APP_VERSION = '0.1'
APP_DESCRIPTION = 'Bitcoin payment orders via XMPP'

class Component(XMPPComponent):
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
        self.admins = set([])
        self.last = {'': datetime.now()}
        self.jid = jid
        self.password = password
        self.connectedUsers = set()
        XMPPComponent.__init__(self, server, port, debug=debuglevel, \
                               domains=[jid])

    def start(self, proxy=None):
        if not self.connect(None, proxy):
            raise Exception('Unable to connect to %s:%s' % (server, port))
        if not self.auth(self.jid, self.password):
            raise Exception('Unable to authenticate as %s' % (jid))
        self._RegisterHandlers()
        debug("Sending initial presence to all contacts...")
        for jid in UserAccount.getAllContacts():
            self.send(Presence(to=jid, frm=self.jid, typ='probe'))
            user = UserAccount(JID(jid))
            self.sendBitcoinPresence(user)
            for addr in user.getRoster():
                self.sendBitcoinPresence(user, addr)

    def _RegisterHandlers(self):
        '''Define the Service Discovery information for automatic handling
           by the xmpp library.
        '''
        self.RegisterHandler(NS_MESSAGE, self.messageReceived)
        self.RegisterHandler(NS_PRESENCE, self.presenceReceived)
        self.RegisterHandler(NS_IQ, self.iqReceived)
        browser = Browser()
        browser.PlugIn(self)
        browser.setDiscoHandler(self.discoReceivedGateway, jid=self.jid)
        browser.setDiscoHandler(self.discoReceivedUserOrAddress)

    def discoReceivedUserOrAddress(self, cnx, iq, what):
        '''Dispatcher for disco queries addressed to a JID hosted at the
           gateway (but not the gateway itself). Calls discoReceivedAddress or
           discoReceivedUser depending on whether the recipient is a Bitcoin
           address or a user.
           You should normally query a user by their username, provided they
           set one. If you're an admin, you can additionally query them from
           their real JID, in any case.
        '''
        to = iq.getTo()
        try:
            address = Address(to)
            return self.discoReceivedAddress(iq, what, address)
        except InvalidBitcoinAddressError:
            try:
                jidprefix = JIDDecode(to.getNode())
                if iq.getFrom().getStripped() in self.admins and (0 <= to.getNode().find('.')):
                    # Treat as JID, and must be registered
                    user = UserAccount(JID(jidprefix), True)
                else:
                    # Treat as username (so must be registered, of course)
                    user = UserAccount(jidprefix)
                return self.discoReceivedUser(iq, what, user)
            except UnknownUserError:
                pass # The default handler will send a "not supported" error

    def sayGoodbye(self):
        '''Ending method. Doesn't do anything interesting yet.'''
        message = 'Service is shutting down. See you later.'
        for user in self.connectedUsers:
            self.send(Presence(to=user.jid, frm=self.jid, typ='unavailable', status=message))
            for addr in user.getRoster():
                self.send(Presence(to=user.jid, frm=addr, typ='unavailable', status=message))
        debug("Bye.")
        self.send('</stream:stream>')

    def sendBitcoinPresence(self, user, fromJID=None):
        '''Send a presence information to the user, from a specific address.
           If address is None, send information from the gateway itself.
        '''
        if not user.isRegistered():
            return
        if fromJID is None:
            fromJID = self.jid
        if fromJID == self.jid:
            username = user.username
            if 0 == len(username):
                status = ''
            else:
                status = 'Hi %s! ' % username
            status += 'Current balance: BTC %s' % user.getBalance()
        else:
            address = Address(fromJID)
            if user.ownsAddress(address):
                status = 'This address is mine'
                percentage = address.getPercentageReceived()
                if percentage is not None:
                    status += '\nReceived %s%% of total balance' % percentage
            else:
                status = None
        self.send(Presence(to=user.jid, typ='available', show='online', status=status, frm=fromJID))

    def addAddressToRoster(self, address, user):
        '''Add the JID corresponding to a given bitcoin address to user's
           roster. The suggested name is the bitcoin address.'''
        debug("Adding address %s to %s's roster")
        msg = 'Hi! I\'m your new Bitcoin address'
        pres = Presence(typ='subscribe', status=msg, frm=address.jid, to=user.jid)
        nick = Node('nick')
        nick.setNamespace(NS_NICK)
        nick.setData(address.address)
        pres.addChild(node=nick)
        self.send(pres)

    def discoReceivedGateway(self, cnx, iq, what):
        user = UserAccount(iq.getFrom())
        node = iq.getQuerynode()
        if 'info' == what:
            if node is None:
                ids = [{'category': 'gateway', 'type': 'bitcoin',
                        'name':APP_DESCRIPTION}]
                return {'ids': ids, 'features': [NS_DISCO_INFO, NS_DISCO_ITEMS, NS_REGISTER, NS_VERSION, NS_GATEWAY, NS_LAST]}
            elif 'users' == node:
                ids = [{'category': 'directory', 'type': 'user', 'name': 'Users'}]
                return {'ids': ids, 'features': [NS_DISCO_INFO, NS_DISCO_ITEMS]}
        elif 'items' == what:
            items = []
            if user.isRegistered():
                if node is None:
                    items.append({'jid': user.getLocalJID(), 'name': 'Your addresses', 'node': 'addresses'})
            else:
                items.append({'jid': self.jid, 'name': APP_DESCRIPTION})
            if user.jid in self.admins:
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

    def discoReceivedUser(self, iq, what, targetUser):
        user = UserAccount(iq.getFrom())
        node = iq.getQuerynode()
        if (user.jid == targetUser.jid) or (user.jid in self.admins):
            if user.jid == targetUser.jid:
                label_addresses = 'Your addresses'
            else:
                label_addresses = 'Their addresses'
            if 'info' == what:
                if node is None:
                    ids = [{'category': 'account', 'type': 'registered', 'name': targetUser.getLabel()}]
                    return {'ids': ids, 'features': [NS_DISCO_INFO, NS_DISCO_ITEMS, NS_VERSION]}
                elif 'addresses' == node:
                    ids = [{'category': 'hierarchy', 'type': 'branch', 'name': label_addresses}]
                    return {'ids': ids, 'features': [NS_DISCO_INFO, NS_DISCO_ITEMS, NS_VERSION]}
            elif 'items' == what:
                items = []
                if node is None:
                    items.append({'jid': targetUser.getLocalJID(), 'name': label_addresses, 'node': 'addresses'})
                    items.append({'jid': targetUser.jid, 'name': 'Real identity'})
                elif 'addresses' == node:
                    for address in targetUser.getAddresses():
                        items.append({'jid': Address(address).jid, 'name': address})
                return items

    def discoReceivedAddress(self, iq, what, address):
        debug("DISCO about an address: %s" % address)
        user = UserAccount(iq.getFrom())
        node = iq.getQuerynode()
        owner = UserAccount(JID(address.account))
        if 'info' == what:
            if node is None:
                ids = [{'category': 'hierarchy', 'type': 'branch', 'name': address.address}]
                return {'ids': ids, 'features': [NS_DISCO_INFO, NS_DISCO_ITEMS, NS_VERSION]}
        elif 'items' == what:
            items = []
            if node is None and ((user.jid == owner.jid) or (user.jid in self.admins)):
                items.append({'jid': owner.getLocalJID(), 'name': 'Owner'})
            return items

    def messageReceived(self, cnx, msg):
        '''Message received'''
        error = None
        user = UserAccount(msg.getFrom())
        debug("Received message from %s" % user)
        if not user.isRegistered():
            error = "You're not registered. Please register, it's free!"
        else:
            if self.jid == msg.getTo().getStripped():
                try:
                    address = Address(msg.getBody())
                    msg = Message(to=msg.getFrom(), frm=address.jid,\
                          body='I\'m %s. Talk to me.' % address, typ='chat')
                    cnx.send(msg)
                    raise NodeProcessed
                except InvalidBitcoinAddressError:
                    try:
                        (action, args) = parseCommand(msg.getBody())
                        reply = Command(action, args).execute(user)
                    except CommandTargetError:
                        error = 'This command only works with an address'
                    except UnknownCommandError:
                        error = ('Unknown command \'%s\'. Type \'%s\' for a ' \
                                 + 'list of accepted commands.') \
                                % (action, COMMAND_HELP)
                    except CommandSyntaxError, reason:
                        error = reason
                    except CommandError, reason:
                        error = reason
            else:
                try:
                    try:
                        address = Address(msg.getTo())
                        (action, args) = parseCommand(msg.getBody())
                        reply = Command(action, args, address).execute(user)
                    except InvalidBitcoinAddressError:
                        # From node to JID back to username: This has the
                        # double advantage to normalize the username and check
                        # whether it exists.
                        username = UserAccount(JIDDecode(msg.getTo().getNode())).username
                        (action, args) = parseCommand(msg.getBody())
                        reply = Command(action, args, username=username).execute(user)
                except UnknownUserError:
                    error = 'This is not a valid user or bitcoin address.'
                except CommandTargetError:
                    error = 'This command only works with the gateway'
                except UnknownCommandError:
                    error = ('Unknown command \'%s\'. Type \'%s\' for a ' \
                             + 'list of accepted commands.') \
                            % (action, COMMAND_HELP)
                except CommandSyntaxError, reason:
                    error = reason
                except CommandError, reason:
                    error = reason
        if error is None:
            msg = msg.buildReply(reply)
            msg.setType('chat')
            if user.checkBalance() is not None:
                self.sendBitcoinPresence(user)
        else:
            msg = msg.buildReply("Error: %s" % error)
            msg.setType('error')
        cnx.send(msg)
        raise NodeProcessed

    # If any presence stanza is received from an unregistered user, don't
    # even look at it. They should register first.
    def presenceReceived(self, cnx, prs):
        '''Presence received'''
        frm = prs.getFrom()
        resource = frm.getResource()
        user = UserAccount(frm)
        to = prs.getTo().getStripped()
        if not user.isRegistered():
            return #TODO: Send a registration-required error
        typ = prs.getType()
        if to == self.jid:
            if typ == 'subscribe':
                cnx.send(Presence(typ='subscribed', frm=to, to=user.jid))
                self.sendBitcoinPresence(user)
            elif typ == 'subscribed':
                debug('We were allowed to see %s\'s presence.' % user)
            elif typ == 'unsubscribe':
                debug('Just received an "unsubscribe" presence stanza. What does that mean?')
            elif typ == 'unsubscribed':
                debug('Unsubscribed. Any interest in this information?')
            elif typ == 'probe':
                self.sendBitcoinPresence(user)
            elif (typ == 'available') or (typ is None):
                self.userResourceConnects(user, resource)
            elif typ == 'unavailable':
                self.userResourceDisconnects(user, resource)
            elif typ == 'error':
                debug('Presence error. TODO: Handle it by not sending presence updates to them until they send a non-error.')
        else:
            try:
                address = Address(JID(prs.getTo()))
            except InvalidBitcoinAddressError:
                debug("Invalid address %s" % prs.getTo())
                raise NodeProcessed # Just drop the case. TODO: Handle invalid addresses better
            if typ == 'subscribe':
                cnx.send(Presence(typ='subscribed', frm=to, to=user.jid))
                self.sendBitcoinPresence(user, prs.getTo())
            elif typ == 'unsubscribe':
                cnx.send(Presence(typ='unsubscribed', frm=to, to=user.jid))
            elif typ == 'probe':
                self.sendBitcoinPresence(user, address.jid)
        raise NodeProcessed

    def iqReceived(self, cnx, iq):
        '''IQ received'''
        typ = iq.getType()
        ns = iq.getQueryNS()
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
                    instructions.setData('You may set/change your username if you wish.')
                    username.setData(user.username)
                else:
                    debug("A new user is preparing a registration")
                    instructions.setData('After registration, you\'ll get a Bitcoin address that you can use to send and receive payments via Bitcoin.\nYou may also choose a username.')
                reply = iq.buildReply('result')
                query = reply.getTag('query')
                if registered:
                    query.addChild(node=Node('registered'))
                query.addChild(node=instructions)
                query.addChild(node=username)
                cnx.send(reply)
                raise NodeProcessed
            else:
                # Unkown namespace and type. The default handler will take care of it if we don't raise NodeProcessed.
                debug("Unknown IQ with ns '%s' and type '%s'." % (ns, typ))
        elif (NS_VERSION == ns) and ('get' == typ):
            name = Node('name')
            name.setData(APP_NAME)
            version = Node('version')
            version.setData(APP_VERSION)
            reply = iq.buildReply('result')
            query = reply.getTag('query')
            query.addChild(node=name)
            query.addChild(node=version)
            cnx.send(reply)
            raise NodeProcessed
        elif NS_GATEWAY == ns:
                if 'get' == typ:
                    desc = Node('desc')
                    desc.setData('Please enter the Bitcoin contact you would like to add.\nYou may enter a Bitcoin address or an existing username.')
                    prompt = Node('prompt')
                    prompt.setData('Bitcoin address')
                    reply = iq.buildReply('result')
                    query = reply.getTag('query')
                    query.addChild(node=desc)
                    query.addChild(node=prompt)
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
                                error = ErrorNode('item-not-found', 404, 'cancel', 'You must give an existing username or a Bitcoin address.')
                                reply.addChild(node=error)
                                cnx.send(reply)
                                raise NodeProcessed
                        reply = iq.buildReply('result')
                        query = reply.getTag('query')
                        query.addChild(node=jid)
                        cnx.send(reply)
                        raise NodeProcessed
        elif (NS_LAST == ns) and ('get' == typ):
            frm = iq.getTo().getNode()
            if frm in self.last:
                reply = iq.buildReply('result')
                query = reply.getTag('query')
                query.setAttr('seconds', (datetime.now() - self.last[frm]).seconds)
                cnx.send(reply)
                raise NodeProcessed
        else:
            debug("Unhandled IQ namespace '%s'." % ns)

    def userResourceConnects(self, user, resource):
        '''Called when the component receives a presence"available" from a
           user. This method first registers the resource. Then, if it's the
           user's first online resource: sends them a presence packet, and
           internally adds them to the list of online users.'''
        debug("New resource (%s) for user %s" % (resource, user))
        user.resourceConnects(resource)
        if not user in self.connectedUsers:
            self.sendBitcoinPresence(user)
            self.connectedUsers.add(user)
            for address in user.getRoster():
                self.sendBitcoinPresence(user, address)

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
            error = ErrorNode('not-acceptable', 500, 'cancel', 'Your JID must contain a dot. That\'s the rule.')
            reply.addChild(node=error)
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
            error = ErrorNode('not-acceptable', 406, 'modify', 'This username is invalid or not available')
            reply.addChild(node=error)
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
        self.send(Presence(to=user.jid, frm=self.jid, typ='unavailable', status='Thanks for using this service. Bye!'))
