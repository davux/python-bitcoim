# -*- coding: utf-8 -*-
# vi: sts=4 et sw=4

from bitcoim.address import Address
from bitcoim.command import Command, parse as parseCommand, COMMAND_HELP, \
                            CommandSyntaxError, CommandTargetError, \
                            CommandError, UnknownCommandError

from bitcoin.address import InvalidBitcoinAddressError
from bitcoin.controller import Controller
from logging import debug, info
from useraccount import UserAccount, AlreadyRegisteredError
from xmpp.client import Component as XMPPComponent
from xmpp.protocol import JID, Message, Iq, Presence, Error, NodeProcessed, \
                          NS_IQ, NS_MESSAGE, NS_PRESENCE, NS_DISCO_INFO, \
                          NS_DISCO_ITEMS, NS_GATEWAY, NS_REGISTER, NS_VERSION
from protocol import NS_NICK
from xmpp.simplexml import Node
from xmpp.browser import Browser

APP_NAME = 'BitcoIM'
APP_IDENTIFIER = 'bitcoim'
APP_VERSION = '0.1'
APP_DESCRIPTION = 'Bitcoin payment orders via XMPP'

class Component:
    '''The component itself.'''

    def __init__(self, jid, password, server, port=5347, debug=[]):
        '''Constructor.
           - Establish a session
           - Declare handlers
           - Send initial presence probe to all users
           - Send initial presence broadcasts to all users, from the gateway
             and from each of their "contacts" (bitcoin addresses)
        '''
        self.bye = False
        Address.domain = jid
        self.cnx = XMPPComponent(jid, port, debug=debug)
        self.jid = jid
        self.connectedUsers = set()
        if not self.cnx.connect([server, port]):
            raise Exception('Unable to connect to %s:%s' % (server, port))
        if not self.cnx.auth(jid, password):
            raise Exception('Unable to authenticate as %s' % (jid))
        self.cnx.RegisterHandler(NS_MESSAGE, self.messageReceived)
        self.cnx.RegisterHandler(NS_PRESENCE, self.presenceReceived)
        self.cnx.RegisterHandler(NS_IQ, self.iqReceived)
        self.handleDisco(self.cnx)
        debug("Sending initial presence to all contacts...")
        for jid in UserAccount.getAllContacts():
            self.cnx.send(Presence(to=jid, frm=self.jid, typ='probe'))
            user = UserAccount(JID(jid))
            self.sendBitcoinPresence(self.cnx, user)
            for addr in user.getRoster():
                self.sendBitcoinPresence(self.cnx, user, addr)

    def handleDisco(self, cnx):
        '''Define the Service Discovery information for automatic handling
           by the xmpp library.
        '''
        browser = Browser()
        browser.PlugIn(cnx)
        ids = [{'category': 'gateway', 'type': 'bitcoin',
               'name':APP_DESCRIPTION}]
        info = {'ids': ids, 'features': [NS_DISCO_INFO, NS_DISCO_ITEMS, NS_REGISTER, NS_VERSION, NS_GATEWAY]}
        items = [{'jid': self.jid, 'name': APP_DESCRIPTION}]
        browser.setDiscoHandler({'items': items, 'info': info})

    def loop(self, timeout=0):
        '''Main loop. Listen to incoming stanzas.'''
        while not self.bye:
            self.cnx.Process(timeout)

    def sayGoodbye(self):
        '''Ending method. Doesn't do anything interesting yet.'''
        message = 'Service is shutting down. See you later.'
        for user in self.connectedUsers:
            self.cnx.send(Presence(to=user.jid, frm=self.jid, typ='unavailable', status=message))
            for addr in user.getRoster():
                self.cnx.send(Presence(to=user.jid, frm=addr, typ='unavailable', status=message))
        debug("Bye.")

    def sendBitcoinPresence(self, cnx, user, fromJID=None):
        '''Send a presence information to the user, from a specific address.
           If address is None, send information from the gateway itself.
        '''
        if not user.isRegistered():
            return
        if fromJID is None:
            fromJID = self.jid
        if fromJID == self.jid:
            status = 'Current balance: BTC %s' % user.getBalance()
        else:
            address = Address(fromJID)
            if user.ownsAddress(address):
                status = 'This address is mine'
                percentage = address.getPercentageReceived()
                if percentage is not None:
                    status += '\nReceived %s%% of total balance' % percentage
            else:
                status = None
        cnx.send(Presence(to=user.jid, typ='available', show='online', status=status, frm=fromJID))

    def addAddressToRoster(self, cnx, address, user):
        '''Add the JID corresponding to a given bitcoin address to user's
           roster. The suggested name is the bitcoin address.'''
        debug("Adding address %s to %s's roster")
        msg = 'Hi! I\'m your new Bitcoin address'
        pres = Presence(typ='subscribe', status=msg, frm=address.jid, to=user.jid)
        nick = Node('nick')
        nick.setNamespace(NS_NICK)
        nick.setData(address.address)
        pres.addChild(node=nick)
        cnx.send(pres)

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
                    address = Address(msg.getTo()).address
                    (action, args) = parseCommand(msg.getBody())
                    reply = Command(action, args, address).execute(user)
                except InvalidBitcoinAddressError:
                    error = 'This is not a valid bitcoin address.'
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
        else:
            try:
                address = Address(JID(prs.getTo()))
            except InvalidBitcoinAddressError:
                debug("Invalid address %s" % prs.getTo())
                raise NodeProcessed # Just drop the case. TODO: Handle invalid addresses better
            if typ == 'subscribe':
                cnx.send(Presence(typ='subscribed', frm=to, to=user.jid))
                self.sendBitcoinPresence(cnx, user, prs.getTo())
            elif typ == 'unsubscribe':
                cnx.send(Presence(typ='unsubscribed', frm=to, to=user.jid))
            elif typ == 'probe':
                self.sendBitcoinPresence(cnx, user, address.jid)
        raise NodeProcessed

    def iqReceived(self, cnx, iq):
        '''IQ received'''
        typ = iq.getType()
        ns = iq.getQueryNS()
        if NS_REGISTER == ns:
            if 'set' == typ:
                children = iq.getQueryChildren()
                if (0 != len(children)) and ('remove' == children[0].getName()):
                    self.unregistrationRequested(cnx, iq)
                else:
                    self.registrationRequested(cnx, iq)
                raise NodeProcessed
            elif 'get' == typ:
                instructions = Node('instructions')
                registered = UserAccount(iq.getFrom()).isRegistered()
                if registered:
                    instructions.setData('There is no registration information to update. Simple as that.')
                else:
                    debug("A new user is preparing a registration")
                    instructions.setData('Register? If you do, you\'ll get a Bitcoin address that you can use to send and receive payments via Bitcoin.')
                reply = iq.buildReply('result')
                query = reply.getTag('query')
                if registered:
                    query.addChild(node=Node('registered'))
                query.addChild(node=instructions)
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
                    desc.setData('Please enter the Bitcoin address you would like to add.')
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
                        try:
                            jid = Node('jid')
                            jid.setData(Address(prompt).jid)
                            reply = iq.buildReply('result')
                            query = reply.getTag('query')
                            query.addChild(node=jid)
                        except InvalidBitcoinAddressError:
                            reply = iq.buildReply('error')
                            debug("TODO: Send an error because the address %s is invalid." % prompt)
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
            self.sendBitcoinPresence(self.cnx, user)
            self.connectedUsers.add(user)
            for address in user.getRoster():
                self.sendBitcoinPresence(self.cnx, user, address)

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
            self.cnx.send(Presence(typ='unavailable', frm=self.jid, to=jid))
            self.connectedUsers.remove(user)
            for address in user.getRoster():
                self.cnx.send(Presence(typ='unavailable', frm=address, to=jid))

    def registrationRequested(self, cnx, iq):
        '''A registration request was received'''
        frm = iq.getFrom()
        info("Registration request from %s" % frm)
        isUpdate = False
        user = UserAccount(frm)
        try:
            user.register()
            new_address = user.createAddress()
            self.addAddressToRoster(cnx, new_address, user)
        except AlreadyRegisteredError:
            info("(actually just an update)")
            isUpdate = True # This would be stupid, since there's no registration info to update
        cnx.send(Iq(typ='result', to=frm, frm=self.jid, attrs={'id': iq.getID()}))
        if not isUpdate:
            cnx.send(Presence(typ='subscribe', to=frm.getStripped(), frm=self.jid))

    def unregistrationRequested(self, cnx, iq):
        '''An unregistration request was received'''
        user = UserAccount(iq.getFrom())
        info("Unegistration request from %s" % frm)
        try:
            user.unregister()
        except AlreadyUnregisteredError:
            pass # We don't really mind about unknown people wanting to unregister. Should we?
        cnx.send(iq.buildReply('result'))
        cnx.send(Presence(to=user.jid, frm=self.jid, typ='unsubscribe'))
        cnx.send(Presence(to=user.jid, frm=self.jid, typ='unsubscribed'))
        cnx.send(Presence(to=user.jid, frm=self.jid, typ='unavailable', status='Thanks for using this service. Bye!'))
