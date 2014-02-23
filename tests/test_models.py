from __future__ import absolute_import
import datetime
import random
import unittest

from google.appengine.ext import testbed
from muninn.models import Event, AgentStore, SourceAgent
from muninn.agents import Agent


class TestAgent(Agent):
    @classmethod
    def run(cls, events, **kwargs):
        print events
        res = []
        for event in events:
            res.append(event.data)
        return res


class MuteAgent(Agent):
    can_generate_events = False

    @classmethod
    def run(cls, data):
        return None


class AgentStoreTestCase(unittest.TestCase):
    '''Tests for Agent model'''
    def setUp(self):
        self.testbed = testbed.Testbed()
        self.testbed.setup_env('muninn')
        self.testbed.activate()
        self.testbed.init_datastore_v3_stub()

    def tearDown(self):
        self.testbed.deactivate()

    def test_list_agents(self):
        for i in range(10):
            agent = AgentStore()
            agent.put()
        agent = AgentStore.query().get()
        agent.is_active = False
        agent.put()
        agents = AgentStore.all()
        self.assertEqual(len(agents), 9)

    def test_agent_events(self):
        source_agent = Agent.new(name='Source Agent')
        listening_agent = Agent.new(name='Listening Agent',
                                    source_agents=[source_agent])
        listening_agent_2 = Agent.new(name='Listening Agent 2',
                                      source_agents=None)
        source_agent.queue_event({'event_field': 'event_value'})
        self.assertIn(listening_agent,
                      SourceAgent.get_listening_agents(source_agent))
        events = listening_agent.check_events()
        self.assertEqual(len(events), 1)
        events = listening_agent_2.check_events()
        self.assertEqual(len(events), 0)

    def test_agent_sources(self):
        source_agent1 = TestAgent.new(name='Source Agent 1')
        source_agent2 = TestAgent.new(name='Source Agent 2')
        mute_agent = MuteAgent.new(name='Mute Agent')
        agent = TestAgent.new(name='Test Agent',
                              source_agents=[source_agent1, source_agent2, mute_agent])
        self.assertEqual(SourceAgent.get_source_agents(agent),
                         [source_agent1, source_agent2])

    def test_agent_run(self):
        source_agent1 = TestAgent.new(name='Source Agent 1')
        source_agent2 = TestAgent.new(name='Source Agent 2')
        agent = TestAgent.new(name='Test Agent',
                              source_agents=[source_agent1, source_agent2])
        listening_agent = TestAgent.new(name='Listening Agent',
                                        source_agents=[agent])
        source_agent1.queue_event(1)
        source_agent2.queue_event(2)
        agent.run()
        generated_events = Event.from_agent(agent)
        self.assertEqual(generated_events[0].data, [1, 2])

if __name__ == '__main__':
    unittest.main()
