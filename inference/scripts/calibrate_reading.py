"""Measure what "usual" means for the brain reading: each region's rattling over many real questions and answers.

The reading says which regions rattled more than usual for this question. "Usual" has to come from real
conversations: measured on a handful of questions, the mushroom body tops nearly every reading, because real
questions always stir it more than the few samples did. This runs the full pipeline (graph + LFM2.5 + adapter)
over the questions below and writes the per-region mean and spread to assets/reading_baseline.npz.
Half of the questions calibrate, the other half check how varied the readings come out.

Needs the runtime data (FLY_ORACLE_HOME). Takes a few minutes on CPU:
    uv run python scripts/calibrate_reading.py
Rerun whenever the graph, prompt, model or region assignment change.
"""
import collections
import json

import numpy as np

from fly_oracle_inference import share
from fly_oracle_inference.oracle import Oracle
from fly_oracle_inference.paths import ASSETS
from fly_oracle_inference.sim import Simulator

QUESTIONS = [
    # Yes or no
    'Should I quit my job?', 'Should I text them back?', 'Is it time to quit my job?', 'Should I adopt a cat?',
    'Should I call my mom?', 'Do aliens exist?', 'Should I buy a dog?', 'Is coffee bad for me?',
    'Should I learn Spanish?', 'Should I go to the party?', 'Am I a good cook?', 'Should I run a marathon?',
    'Is my ex thinking of me?', 'Should I dye my hair blue?', 'Is it time to sleep?', 'Should I eat a banana?',
    'Should I start a business?', 'Can flies dance?', 'Should I move to Berlin?', 'Should I buy bitcoin?',
    'Do you like music?', 'Should I take a nap?', 'Is the sky blue?', 'Will I be rich one day?',
    'Should I get a tattoo?', 'Is it okay to eat cake for breakfast?', 'Should I ask for a raise?',
    'Will it rain tomorrow?', 'Should I go back to school?', 'Is my cat plotting against me?',
    'Should I sell my car?', 'Should I learn the guitar?', 'Is it too late to start piano at 40?',
    'Should I propose this weekend?', 'Am I overthinking this?', 'Should I go to the gym today?',
    'Should I forgive my friend?', 'Is today a lucky day?', 'Should I cut my hair short?',
    'Should I watch one more episode?', 'Do you dream at night?', 'Are you smarter than me?',
    'Should I apologize first?', 'Should I wake up earlier?', 'Can I trust my neighbour?',
    'Should I paint my room yellow?', 'Is chess a sport?', 'Should I delete my social media?',
    'Should I travel alone?', 'Should I plant tomatoes this year?',
    # This or that
    'Pizza or sushi tonight?', 'Tea or coffee?', 'Cats or dogs?', 'Beach or mountains?', 'Summer or winter?',
    'Chocolate or vanilla?', 'Netflix or a book?', 'Train or plane to Paris?', 'Red or blue shirt?',
    'Apple or banana?', 'City or countryside?', 'Early bird or night owl?', 'Rent or buy a flat?',
    'Bike or bus to work?', 'Pancakes or waffles?', 'Rock or jazz?', 'Stay in or go out tonight?',
    'Text or call?', 'Mac or Windows?', 'Hiking or swimming this weekend?', 'Pasta or rice?',
    'Big party or small dinner for my birthday?', 'Left or right?', 'Sweet or salty snack?', 'Dog or cat name: Max or Luna?',
    # Open
    'What should I cook tonight?', 'What is the meaning of life?', 'What should I do this weekend?',
    'Where should I go on holiday?', 'What should I name my plant?', 'What gift should I buy my dad?',
    'How do I make new friends?', 'What should I read next?', 'What hobby should I start?',
    'How can I sleep better?', 'What should I wear to the interview?', 'What is your favourite fruit?',
    'What should I study?', 'How do I stop procrastinating?', 'What colour should my new car be?',
    'What film should I watch tonight?', 'Where do flies go in winter?', 'What makes you happy?',
    'How do I impress my crush?', 'What should I have for breakfast?', 'What is the best smell in the world?',
    'How do I win at board games?', 'What should my band be called?', 'Which city should I visit next?',
    'What should I do when I am bored?',
    # Other languages
    'Soll ich heute ins Kino gehen?', 'Soll ich ein neues Velo kaufen?', 'Ist Fondue besser als Raclette?',
    'Soll ich meinen Job kündigen?', 'Was soll ich heute kochen?', 'Soll ich Ferien am Meer machen?',
    'Bin ich ein guter Freund?', 'Soll ich mir eine Katze holen?', 'Kaffee oder Tee am Morgen?',
    'Wird es morgen regnen?', '¿Debo aprender a bailar salsa?', '¿Pizza o tacos esta noche?',
    '¿Voy a ser feliz?', 'Dois-je déménager à Paris?', 'Croissant ou pain au chocolat?',
    'Devo comprare una moto?', 'Pasta o pizza stasera?', 'Moet ik een hond nemen?', 'Должен ли я учить китайский?',
    'Should I eat the last cookie?',
    # Silly and odd
    'Are you really a fly?', 'Can you see the future?', 'What is 2 plus 2?', 'Do you like humans?',
    'Should I build a giant robot?', 'Is the moon made of cheese?', 'Would you rather fly or swim?',
    'Is a hot dog a sandwich?', 'Should I name my son after a fly?', 'Can I have a pet dragon?',
    'Should I wear socks with sandals?', 'Is it rude to eat the last slice?', 'Should I learn to juggle?',
    'Is pineapple on pizza okay?', 'Should I dance in the rain?', 'Do fruit flies like bananas?',
    'Should I write a book about flies?', 'Are clowns scary?', 'Should I start a podcast?',
    'Is it a good day to buy shoes?', 'Should I adopt a goldfish?', 'Can you keep a secret?',
    'Should I learn to code?', 'Will my team win the game?', 'Should I go skydiving?',
]


def measure(sim, oracle, question):
    """Summed state change per neuron over the question and the answer, as the server's think() does."""
    ids = sim.question_ids(question)
    total, steps, last = 0, 0, None
    for last in sim.steps(ids):
        total, steps = total + last.change, steps + 1
    x = last.state

    def graph_step(token):
        nonlocal x
        step = sim.step(x, token)
        x = step.state
        return step.features, step.change

    for _, change in oracle.answer(ids, last.features, graph_step, question):
        total, steps = total + change, steps + 1
    return total, steps


def main():
    sim = Simulator()
    newline = [i for i in range(sim.tokenizer.get_vocab_size()) if '\n' in sim.tokenizer.decode([i])]
    oracle = Oracle(sim.embeddings, sim.system_ids, set(newline))
    sim.baseline = None  # measure against nothing; readings below use the new baseline

    regional, totals = [], []
    for k, q in enumerate(QUESTIONS):
        total, steps = measure(sim, oracle, q)
        regional.append(sim._regional(total) / steps)
        totals.append((total, steps))
        print(f'{k + 1}/{len(QUESTIONS)}', flush=True)
    regional = np.array(regional)

    calibrate, check = regional[0::2], range(1, len(QUESTIONS), 2)
    baseline = {'mean': calibrate.mean(axis=0), 'std': calibrate.std(axis=0) + 1e-12}
    np.savez(ASSETS / 'reading_baseline.npz', **baseline)
    sim.baseline = baseline

    # How varied are the readings on the questions the baseline hasn't seen?
    kinds, tops = collections.Counter(), collections.Counter()
    for k in check:
        reading = sim.reading(*totals[k])
        kinds[share.decision(reading)['id']] += 1
        tops[sim.region_names[reading[0]['region']]] += 1
        print(QUESTIONS[k][:40].ljust(40), share.decision(reading)['title'],
              [(sim.region_names[r['region']], r['factor']) for r in reading], flush=True)
    print(json.dumps({'decisions': kinds.most_common(), 'top_regions': tops.most_common(15)}, indent=1))


if __name__ == '__main__':
    main()
