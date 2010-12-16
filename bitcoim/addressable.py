from xmpp.protocol import NS_DISCO_INFO

'''
   This module represent any object that is addressable in the scope of the
   component.
'''

class Addressable(object):
    '''An addressable object'''

    def discoInfo(self, user, what, node=None):
        '''Default method, sends nothing interesting.
           - user: the UserAccount doing the request
           - what: 'info' or 'items'
           - node: what node was requested
        '''
        if 'info' == what:
            ids = [{'category': 'hierarchy', 'type': 'leaf'}]
            return {'ids': ids, 'features': [NS_DISCO_INFO]}
