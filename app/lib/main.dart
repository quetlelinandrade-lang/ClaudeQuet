import 'package:flutter/material.dart';

import 'src/screens/home_screen.dart';

void main() {
  runApp(const ParentalMonitorApp());
}

class ParentalMonitorApp extends StatelessWidget {
  const ParentalMonitorApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Monitoramento Infantil',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF3B6FE0)),
        useMaterial3: true,
      ),
      home: const HomeScreen(),
    );
  }
}
