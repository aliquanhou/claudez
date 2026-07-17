# test_probe.py
import sys, os
sys.path.insert(0, 'D:\\ClaudeZ')
os.chdir('D:\\ClaudeZ')

from agent.plugins.host_tools.plugin import Plugin, get_plugin_debug

p = Plugin()
p._load_probe_rules()
print('RULES:', len(p._probe_rules))
print('MASKED:', p._masked)

p.probe(True)
print('CACHED:', list(p._cache.keys()))

logs = get_plugin_debug()
for l in logs[-20:]:
    print('  [%s] %s' % (l['event'], l['msg']))

print('---get_tools---')
for t in p.get_tools():
    print('  %s v%s' % (t['name'], t['version']))

print('---get_all_probed---')
for t in p.get_all_probed():
    print('  %s v%s masked=%s' % (t['name'], t['version'], t['masked']))
