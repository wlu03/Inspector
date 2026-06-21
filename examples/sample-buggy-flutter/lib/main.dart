import 'package:flutter/material.dart';

void main() => runApp(const BuggyApp());

class BuggyApp extends StatelessWidget {
  const BuggyApp({super.key});
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Sample Buggy Flutter',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(useMaterial3: true, colorSchemeSeed: Colors.indigo),
      home: const CounterPage(),
    );
  }
}

/// A deterministic counter screen with three planted, visually-observable bugs.
/// Flutter renders to a canvas, so the iOS a11y tree is sparse — an agent must
/// read the SCREENSHOT (vision/OmniParser grounding) to catch these.
class CounterPage extends StatefulWidget {
  const CounterPage({super.key});
  @override
  State<CounterPage> createState() => _CounterPageState();
}

class _CounterPageState extends State<CounterPage> {
  int _count = 0;
  bool _subscribed = false;

  // BUG-01: "Plus" increments by 2 instead of 1.
  void _increment() => setState(() => _count += 2);
  void _decrement() => setState(() => _count -= 1);
  // BUG-02: "Reset" sets the count to 1 instead of 0.
  void _reset() => setState(() => _count = 1);

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Counter')),
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Text('Current count:'),
            Text('$_count', style: Theme.of(context).textTheme.displayLarge),
            const SizedBox(height: 24),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                ElevatedButton(onPressed: _decrement, child: const Text('Minus')),
                const SizedBox(width: 16),
                ElevatedButton(onPressed: _increment, child: const Text('Plus')),
              ],
            ),
            const SizedBox(height: 16),
            OutlinedButton(onPressed: _reset, child: const Text('Reset')),
            const SizedBox(height: 32),
            SizedBox(
              width: 280,
              // BUG-03: tapping the switch flips the label text but never the
              // switch value — the control and its label visibly disagree.
              child: SwitchListTile(
                title: Text(_subscribed ? 'Subscribed' : 'Not subscribed'),
                value: _subscribed,
                onChanged: (_) => setState(() {}),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
