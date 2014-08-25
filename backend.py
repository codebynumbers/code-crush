import gevent
import simplejson as json


class Backend(object):
    """Interface for registering and updating WebSocket clients."""

    def __init__(self, redis, channel):
        # map of room => clients[]
        self.room_clients = {}
        self.pubsub = redis.pubsub()
        self.pubsub.subscribe(channel)

    def __iter_data(self):
        for message in self.pubsub.listen():
            data = message.get('data')
            if message['type'] == 'message':
                #app.logger.info(u'Sending message: {}'.format(data))
                yield data

    def register(self, client, room):
        """Register a WebSocket connection for Redis updates."""
        """
        room_clients = {
            'default': [ws_client_0, ws_client_1, ...],
            'misc': [ws_client_2, ws_client_3, ...]
        } 
        """
        if not self.room_clients.get(room):
            self.room_clients[room] = []
        if client not in self.room_clients[room]:
            self.room_clients[room].append(client)

    def send(self, client, room, data):
        """Send given data to the registered client.
        Automatically discards invalid connections."""
        try:
            client.send(data)
        except Exception:
            # find client's room and remove them from appropriate list
            self.room_clients[room].remove(client)

    def run(self):
        """Listens for new messages in Redis, and sends them to clients."""
        for data in self.__iter_data():
            room = json.loads(data)['room']
            for client in self.room_clients.get(room, []):
                gevent.spawn(self.send, client, room, data)

    def start(self):
        """Maintains Redis subscription in the background."""
        gevent.spawn(self.run)