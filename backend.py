import gevent

class Backend(object):
    """Interface for registering and updating WebSocket clients."""

    def __init__(self, redis, channel):
        # map of room => clients[]
        self.room_clients = {}
        # map of clients => room
        self.client_room = {}

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
        if not self.room_clients.get(room):
            self.room_clients[room] = []
        self.room_clients[room].append(client)
        self.client_room[client] = room

    def send(self, client, data):
        """Send given data to the registered client.
        Automatically discards invalid connections."""
        try:
            client.send(data)
        except Exception:
            # find client's room and remove them from appropriate list
            room = self.client_room[client]
            self.room_clients[room].remove(client)

    def run(self):
        """Listens for new messages in Redis, and sends them to clients."""
        for data in self.__iter_data():
            room = json.loads(data)['room']
            for client in self.room_clients.get(room, []):
                gevent.spawn(self.send, client, data)

    def start(self):
        """Maintains Redis subscription in the background."""
        gevent.spawn(self.run)