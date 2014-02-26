import datetime
import logging
from importlib import import_module
from google.appengine.ext import ndb


def cls_from_name(name):
    parts = name.rsplit('.', 1)
    cls = getattr(import_module(parts[0]), parts[1])
    return cls


class AgentStore(ndb.Model):
    name = ndb.StringProperty()
    type = ndb.StringProperty()
    is_active = ndb.BooleanProperty(default=True)
    last_run = ndb.DateTimeProperty()
    next_run = ndb.DateTimeProperty()
    config = ndb.JsonProperty()
    can_receive_events = ndb.BooleanProperty(default=True)
    can_generate_events = ndb.BooleanProperty(default=True)
    is_running = ndb.BooleanProperty(default=False)

    def __init__(self, **kwargs):
        self._new_events_queue = []
        return super(AgentStore, self).__init__(**kwargs)

    @classmethod
    def new(cls, name, agent_cls, source_agents=None, config=config):
        if source_agents is None or not agent_cls.can_receive_events:
            source_agents = []
        agent = cls(
            name=name,
            type=agent_cls.__module__ + '.' + agent_cls.__name__,
            can_receive_events=agent_cls.can_receive_events,
            can_generate_events=agent_cls.can_generate_events,
            config=config
        )
        agent.put()
        if source_agents:
            source_agent_keys = []
            for source_agent in source_agents:
                if not source_agent.can_generate_events:
                    continue
                key = SourceAgent(
                    agent=agent.key,
                    source=source_agent.key
                )
                source_agent_keys.append(key)
            ndb.put_multi(source_agent_keys)
        return agent

    @classmethod
    def all(cls, type=None, name=None):
        filters = [cls.is_active == True]
        if type is not None:
            filters.append(cls.type == type)
        if name is not None:
            filters.append(cls.name == name)
        return cls.query(*filters).fetch()

    @classmethod
    def due(cls, time):
        agents = cls.query(
            cls.next_run <= time,
            cls.is_running == False,
            cls.is_active == True
        ).fetch()
        return agents

    def _put_events_queue(self):
        '''
        Save any queued events into the datastore
        '''
        events = []
        for event_data in self._new_events_queue:
            if event_data is None:
                return
            if not self.can_generate_events:
                return
            listening_agents = SourceAgent.get_listening_agents(self)

            for agent in listening_agents:
                event = Event(data=event_data,
                              source=self.key,
                              target=agent.key)
                events.append(event)
        ndb.put_multi(events)
        self._new_events_queue = []

    def receive_events(self, source_agents=None):
        '''
        Get events queued by the agents this agent is listening to
        '''
        # TODO: allow specifying limited sources
        if not self.can_receive_events:
            return []
        if source_agents is None:
            source_agents = SourceAgent.get_source_agents(self)
        return Event.for_agent(self, source_agents)

    def add_event(self, data):
        '''
        Add an event to this agent's event queue, but don't
        put it into the datastore yet
        '''
        self._new_events_queue.append(data)

    def run(self):
        '''
        Run this agent's logic
        '''
        if not self.is_active:
            return
        self.is_running = True
        self.put()
        try:
            agent_cls = cls_from_name(self.type)
            events = self.receive_events()
            self._new_events_queue = []
            agent = agent_cls(self)
            result = agent.run(events)
            if result is not None:
                self.add_event(result)
            self._put_events_queue()
        finally:
            self.last_run = datetime.datetime.now()
            self.is_running = False
            self.put()

    def receive_webhook(self, request, response):
        '''
        Run this agent's logic
        '''
        if not self.is_active:
            response.set_status(404)
            return

        self.is_running = True
        self.put()
        try:
            agent_cls = cls_from_name(self.type)
            self._new_events_queue = []
            agent = agent_cls(self)
            agent.receive_webhook(request, response)
        finally:
            self.last_run = datetime.datetime.now()
            self.is_running = False
            self.put()


class Event(ndb.Model):
    data = ndb.JsonProperty()
    source = ndb.KeyProperty(kind=AgentStore)
    target = ndb.KeyProperty(kind=AgentStore)
    is_done = ndb.BooleanProperty(default=False)

    @classmethod
    def for_agent(cls, agent, source_agents, limit=25):
        '''
        Get events for an agent from a list of source_agents
        '''
        # TODO: paginate?
        events = Event.query(Event.is_done == False,
                             Event.target == agent.key)
        if source_agents:
            # so if source_agents is empty, get all events for agent
            source_agents = [s.key for s in source_agents]
            events = events.filter(Event.source.IN(source_agents))
        return events.fetch(limit=limit)

    @classmethod
    def for_agent_from_source(cls, agent, source_agent, limit=25):
        '''
        Get events for an agent from a single source_agent
        '''
        # TODO: paginate?
        events = Event.query(Event.is_done == False,
                             Event.target == agent.key,
                             Event.source == source_agent.key)
        return events.fetch(limit=limit)

    @classmethod
    def from_agent(cls, agent, limit=25):
        '''
        Get events generated by an agent
        '''
        # TODO: paginate?
        events = Event.query(Event.is_done == False,
                             Event.source == agent.key)
        return events.fetch(limit=limit)

    def done(self):
        self.is_done = True
        self.put()


class SourceAgent(ndb.Model):
    agent = ndb.KeyProperty(kind=AgentStore)
    source = ndb.KeyProperty(kind=AgentStore)

    @classmethod
    def get_listening_agents(cls, source_agent):
        '''
        Return a list of agents that are listening for
        events from souce_agent.
        '''
        agents = cls.query(
            SourceAgent.source == source_agent.key
        ).fetch()
        keys = [a.agent for a in agents]
        return ndb.get_multi(keys)

    @classmethod
    def get_source_agents(cls, agent):
        '''
        Return a list of agents that agent is
        listening to for events.
        '''
        agents = cls.query(
            SourceAgent.agent == agent.key
        ).fetch()
        keys = [a.source for a in agents]
        return ndb.get_multi(keys)

