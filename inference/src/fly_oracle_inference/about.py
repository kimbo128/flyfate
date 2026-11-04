"""/how-it-works: the long version of the app's "How it works" dialog, as a crawlable page with FAQ data.

The app is a 3D canvas, so search engines see little of it. This page carries the words people search for:
fruit fly connectome, MaleCNS, talking to a fly brain.
"""
import html

from . import archive, share

TITLE = 'How FlyFate works: a fruit fly connectome that answers questions'
DESCRIPTION = ('Melanie runs on the real MaleCNS wiring diagram of a male fruit fly: 166,700 neurons and 25.6 million '
               'connections. Here is what happens to your question, and what the fly brain really changes.')

# (question, answer) in plain words. Answers are HTML-free text: they go into the FAQ data as they are.
FAQ = [
    ('What is a connectome?',
     'A complete map of every nerve cell in a brain and every connection between them. Scientists cut a fly\'s '
     'brain and nerve cord into thousands of thin slices, imaged them with an electron microscope and traced each '
     'neuron by hand and machine. The male fruit fly connectome, MaleCNS, has 166,700 neurons and 25.6 million '
     'connections.'),
    ('Is Melanie a real fly?',
     'Her brain wiring is real: it is the MaleCNS map of one male fruit fly, Drosophila melanogaster. Melanie herself '
     'is a simulation. Her neurons are not modelled in biological detail, the map just decides which neurons pass '
     'signals to which.'),
    ('What happens to my question?',
     'Every word of your question becomes a small push into the whole wiring diagram, one step per word, and the '
     'activity spreads along the real connections. The 3D brain shows where a step shakes things up more than in '
     'the rest of the brain. Each bead is one real neuron, placed where its synapses are.'),
    ('Who writes the answer?',
     'A small language model, LFM2.5 by Liquid AI. A tiny trained add-on (278,528 numbers) reads the fly brain\'s '
     'activity after every word and nudges which word comes next. It changes about one word in a hundred.'),
    ('Does the fly brain make the answers better?',
     'Barely. In our test on 24 held-back conversations the add-on with the fly brain did slightly better than no '
     'add-on, and just as well as the same add-on without a fly brain. The authors of the underlying FLM project '
     'found no evidence that the connectome itself helps either. It is just more fun this way.'),
    ('What does the brain reading mean?',
     'After each answer Melanie shows which brain regions rattled most unusually, compared with how they behave '
     'across many other questions, and the real cell types that led. The decision type is named after the brain '
     'system of the region that stood out most. The differences are small, a few percent. It tells you what the '
     'wiring did, not what Melanie thinks.'),
    ('Why do I get the same answer when I ask again?',
     'The answer is seeded by the question, so the same question always gets the same answer and the same link. '
     'Ask it differently and the fly may decide differently.'),
    ('Is my question public?',
     'No. Every answer has its own link, but it only appears in the archive and in search engines when someone '
     'shares it or saves it to the archive, and only if it is clean. We count visits without cookies and never '
     'store IP addresses.'),
]

CREDITS = [
    ('Brain data', 'MaleCNS v1.0, FlyEM / HHMI Janelia, University of Cambridge, MRC LMB and Google Research, '
                   'CC BY 4.0.'),
    ('Fly model', 'FLM by nftechie, MIT licence.'),
    ('Language model', 'LFM2.5-1.2B-Instruct by Liquid AI, LFM Open License v1.0.'),
]


def render(base):
    e = html.escape
    url = f'{base}/how-it-works'
    ld = [
        {'@context': 'https://schema.org', '@type': 'FAQPage', 'url': url, 'mainEntity': [
            {'@type': 'Question', 'name': q, 'acceptedAnswer': {'@type': 'Answer', 'text': a}} for q, a in FAQ]},
        {'@context': 'https://schema.org', '@type': 'BreadcrumbList', 'itemListElement': [
            {'@type': 'ListItem', 'position': 1, 'name': 'FlyFate', 'item': f'{base}/'},
            {'@type': 'ListItem', 'position': 2, 'name': 'How it works', 'item': url}]},
    ]
    head = share.head_tags(share.clip(TITLE, 90), share.clip(DESCRIPTION, 200), url,
                           f'{base}/card.jpg?v={share.CARD_VERSION}', ld=ld)
    faq = ''.join(f'<section class="qa"><h2>{e(q)}</h2><p>{e(a)}</p></section>' for q, a in FAQ)
    credits = ''.join(f'<li><strong>{e(k)}:</strong> {e(v)}</li>' for k, v in CREDITS)
    main = f'''
      <section class="intro">
        <span class="tag">How it works</span>
        <h1>A real fruit fly brain answers your question</h1>
        <p class="line">Melanie's brain is the wiring diagram of a male fruit fly: 166,700 neurons, 25.6 million
        connections.</p>
        <p>Ask her anything. Every word runs through all of them, a 3D brain shows where it rattles, and she gives
        her verdict. It is a toy, built on real science, and honest about what the fly does and doesn't do.</p>
        <a class="button" href="/">Ask Melanie</a>
      </section>
      <div class="faq">{faq}
        <section class="qa"><h2>Credits</h2><ul>{credits}</ul></section>
      </div>
      <p class="status"><a href="/answers">Browse the answers people shared</a></p>'''
    return archive.layout(head, main)
