from .ApiBase import ApiBase
import logging
logger = logging.getLogger(__name__)

class ModApiConnector(ApiBase):
    def __init__(self, dispatch):
        ApiBase.__init__(self, '/data/mod')
        self.dispatch = dispatch

    def requestData(self):
        self.request({}, self.handleData)
    
    def requestMod(self, query={}):
        self.request(query, self.handleData)

    def handleData(self, message, meta):
        if len(meta)>0:
            data = dict(
                 command = 'vault_meta'
                ,page = meta['meta']['page']
            )
            self.dispatch.dispatch(data)
        for mod in message:
            preparedData = dict(
                 command = 'modvault_info'
                ,name = mod['displayName']
                ,uid = mod['latestVersion']['uid']
                ,link = mod['latestVersion']['downloadUrl']
                ,description = mod['latestVersion']['description']
                ,author = mod['author']
                ,version = mod['latestVersion']['version']
                ,ui = mod['latestVersion']['type'] == 'UI'
                ,thumbnail = mod['latestVersion']['thumbnailUrl']
                ,date = mod['latestVersion']['updateTime']
                ,rating = 0
                ,reviews = 0
            )
            if len(mod['reviewsSummary']) > 0:
                score = mod['reviewsSummary']['score']
                reviews = mod['reviewsSummary']['reviews']
                if reviews > 0:
                    preparedData['rating'] = float('{:1.2f}'.format(score/reviews))
                    preparedData['reviews'] = reviews
            self.dispatch.dispatch(preparedData)

class MapApiConnector(ApiBase):
    def __init__(self, dispatch):
        ApiBase.__init__(self, '/data/map')
        self.dispatch = dispatch
    
    def requestData(self, query={}):
        self.request(query, self.handleData)

    def handleData(self, message, meta):
        if len(meta)>0:
            data = dict(
                 command = 'vault_meta'
                ,page = meta['meta']['page']
            )
            self.dispatch.dispatch(data)
        for _map in message:
            preparedData = dict(
                 command = 'mapvault_info'
                ,name = _map['displayName']
                ,folderName = _map['latestVersion']['folderName']
                ,link = _map['latestVersion']['downloadUrl']
                ,description = _map['latestVersion']['description']
                ,maxPlayers = _map['latestVersion']['maxPlayers']
                ,version = _map['latestVersion']['version']
                ,ranked = _map['latestVersion']['ranked']
                ,thumbnailSmall = _map['latestVersion']['thumbnailUrlSmall']
                ,thumbnailLarge = _map['latestVersion']['thumbnailUrlLarge']
                ,date = _map['latestVersion']['updateTime']
                ,height = _map['latestVersion']['height']
                ,width = _map['latestVersion']['width']
                ,rating = 0
                ,reviews = 0
            )
            if len(_map['reviewsSummary']) > 0:
                score = _map['reviewsSummary']['score']
                reviews = _map['reviewsSummary']['reviews']
                if reviews > 0:
                    preparedData['rating'] = float('{:1.2f}'.format(score/reviews))
                    preparedData['reviews'] = reviews
            self.dispatch.dispatch(preparedData)

class MapPoolApiConnector(ApiBase):
    def __init__(self, dispatch):
        ApiBase.__init__(self, '/data/mapPoolAssignment')
        self.dispatch = dispatch
    
    def requestData(self, query={}):
        self.request(query, self.handleData)
    
    def handleData(self, message, meta):
        if len(meta)>0:
            data = dict(
                 command = 'vault_meta'
                ,page = meta['meta']['page']
            )
            self.dispatch.dispatch(data)
        for data in message:
            if len(data['mapVersion']) > 0:
                _map = data['mapVersion']
                preparedData = dict(
                     command = 'mapvault_info'
                    ,name = _map['map']['displayName']
                    ,folderName = _map['folderName']
                    ,link = _map['downloadUrl']
                    ,description = _map['description']
                    ,maxPlayers = _map['maxPlayers']
                    ,version = _map['version']
                    ,ranked = _map['ranked']
                    ,thumbnailSmall = _map['thumbnailUrlSmall']
                    ,thumbnailLarge = _map['thumbnailUrlLarge']
                    ,date = _map['updateTime']
                    ,height = _map['height']
                    ,width = _map['width']
                    ,rating = 0
                    ,reviews = 0
                )
                if len(_map['reviewsSummary']) > 0:
                    score = _map['reviewsSummary']['score']
                    reviews = _map['reviewsSummary']['reviews']
                    if reviews > 0:
                        preparedData['rating'] = float('{:1.2f}'.format(score/reviews))
                        preparedData['reviews'] = reviews
            elif data['mapParams'] is not None:
                _map = data['mapParams']
                preparedData = dict(
                     command = 'mapvault_info'
                    ,name = "Neroxis Map Generator"
                    ,folderName = 'neroxis_map_generator_{}_size={}km_spawns={}'.format(_map['version'],
                                                                                         int(_map['size']/51.2),
                                                                                         _map['spawns'])
                    ,link = ''
                    ,description = 'Randomly generated map'
                    ,maxPlayers = _map['spawns']
                    ,version = '1'
                    ,ranked = True
                    ,thumbnailSmall = ''
                    ,thumbnailLarge = ''
                    ,date = ''
                    ,height = _map['size']
                    ,width = _map['size']
                    ,rating = 0
                    ,reviews = 0
                )
            self.dispatch.dispatch(preparedData)
