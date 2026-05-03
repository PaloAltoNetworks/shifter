# Polaris range health report

Generated: 2026-04-15T19:43:54+00:00 / 15:43 EDT

## Summary

- Discovered polaris-vm ranges: 112
- Checked: 112
- Healthy: **108**
- With issues: **4**
- Unreachable (SSM failure): 0

## Issues

| range | user | instance | problems |
|---|---|---|---|
| 65 | 48 | i-0f2d5d02b21fd947d | missing /etc/profile.d/claude-bedrock.sh; missing env CLAUDE_CODE_USE_BEDROCK; missing env AWS_REGION; missing env ANTHROPIC_MODEL; missing env ANTHROPIC_SMALL_FAST_MODEL; missing /etc/hosts bedrock-runtime entry |
| 82 | 18 | i-0c302cfa5355dcccd | missing /etc/profile.d/claude-bedrock.sh; missing env CLAUDE_CODE_USE_BEDROCK; missing env AWS_REGION; missing env ANTHROPIC_MODEL; missing env ANTHROPIC_SMALL_FAST_MODEL; missing /etc/hosts bedrock-runtime entry |
| 95 | 75 | i-0eb833f2f05daffc7 | missing /etc/profile.d/claude-bedrock.sh; missing env CLAUDE_CODE_USE_BEDROCK; missing env AWS_REGION; missing env ANTHROPIC_MODEL; missing env ANTHROPIC_SMALL_FAST_MODEL; missing /etc/hosts bedrock-runtime entry |
| 136 | 113 | i-0ef2920d484b1d941 | missing /etc/profile.d/claude-bedrock.sh; missing env CLAUDE_CODE_USE_BEDROCK; missing env AWS_REGION; missing env ANTHROPIC_MODEL; missing env ANTHROPIC_SMALL_FAST_MODEL; missing /etc/hosts bedrock-runtime entry |

## All ranges

| range | user | instance | ok | containers | a14 | splice-watcher | shard model |
|---|---|---|---|---|---|---|---|
| 27 | 14 | i-0bc65ab42d310e96e | 🟢 | 22/22 | running | active | - |
| 28 | 15 | i-0a21f7be29167a9fc | 🟢 | 22/22 | running | active | - |
| 29 | 24 | i-0c818ad5c40486822 | 🟢 | 22/22 | running | active | - |
| 30 | 114 | i-00d60f9b33e3ac43b | 🟢 | 22/22 | running | active | - |
| 31 | 115 | i-0e613537785a822d8 | 🟢 | 22/22 | running | active | - |
| 32 | 116 | i-047e7a40d549b3b9f | 🟢 | 22/22 | running | active | - |
| 33 | 117 | i-067caf0315f7dbaf3 | 🟢 | 22/22 | running | active | - |
| 34 | 118 | i-0c7c64413723a0e63 | 🟢 | 22/22 | running | active | - |
| 35 | 119 | i-0341216e4f253b8f0 | 🟢 | 22/22 | running | active | - |
| 36 | 120 | i-01af8768386c4f7ba | 🟢 | 22/22 | running | active | - |
| 37 | 121 | i-00b2e7c82d5108346 | 🟢 | 22/22 | running | active | - |
| 38 | 122 | i-07991f2f3b82a572e | 🟢 | 22/22 | running | active | - |
| 39 | 123 | i-00d63692d122ea8ef | 🟢 | 22/22 | running | active | - |
| 40 | 25 | i-05303ecf098c69bc1 | 🟢 | 22/22 | running | active | - |
| 41 | 124 | i-0dcf7db5aa9e38c57 | 🟢 | 22/22 | running | active | - |
| 42 | 26 | i-08e0bb09bef2bf5c9 | 🟢 | 22/22 | running | active | - |
| 43 | 27 | i-0a3a708695e506abb | 🟢 | 22/22 | running | active | - |
| 44 | 28 | i-0e7c157f28c3d5329 | 🟢 | 22/22 | running | active | - |
| 45 | 29 | i-0a8947f2c1e9afd25 | 🟢 | 22/22 | running | active | - |
| 46 | 30 | i-0c8aef9f463483cc5 | 🟢 | 22/22 | running | active | - |
| 47 | 31 | i-084d0a37ef6da1c6a | 🟢 | 22/22 | running | active | - |
| 48 | 32 | i-0832050ac4bafc296 | 🟢 | 22/22 | running | active | - |
| 49 | 33 | i-0e568912cfaf7b2b7 | 🟢 | 22/22 | running | active | - |
| 50 | 34 | i-013cd37052a56d3c3 | 🟢 | 22/22 | running | active | - |
| 51 | 35 | i-0453fc19cc904813c | 🟢 | 22/22 | running | active | - |
| 52 | 36 | i-011cc2bbc5c79a105 | 🟢 | 22/22 | running | active | - |
| 53 | 37 | i-0b308a9ac625b5ff2 | 🟢 | 22/22 | running | active | - |
| 54 | 38 | i-02de38b49e77f2e53 | 🟢 | 22/22 | running | active | - |
| 55 | 39 | i-0ef031b19627ab70f | 🟢 | 22/22 | running | active | - |
| 56 | 40 | i-022dce436473059b1 | 🟢 | 22/22 | running | active | - |
| 57 | 41 | i-0271cc2e3fab2aa75 | 🟢 | 22/22 | running | active | - |
| 58 | 42 | i-05c0285b5758d9eb9 | 🟢 | 22/22 | running | active | - |
| 59 | 43 | i-0feb1ac5f07b1d4d2 | 🟢 | 22/22 | running | active | - |
| 60 | 16 | i-0a7be036bafb4309c | 🟢 | 22/22 | running | active | - |
| 61 | 44 | i-089ff93b80aba5c94 | 🟢 | 22/22 | running | active | - |
| 62 | 45 | i-00620f3181fdd150f | 🟢 | 22/22 | running | active | - |
| 63 | 46 | i-01ac914a77d886832 | 🟢 | 22/22 | running | active | - |
| 64 | 47 | i-02fc7ebcac00215b8 | 🟢 | 22/22 | running | active | - |
| 65 | 48 | i-0f2d5d02b21fd947d | 🔴 | 22/22 | running | active | - |
| 66 | 49 | i-02e01481376ca0951 | 🟢 | 22/22 | running | active | - |
| 67 | 50 | i-0d9b711683c7fafc2 | 🟢 | 22/22 | running | active | - |
| 68 | 51 | i-0822048425a0436d9 | 🟢 | 22/22 | running | active | - |
| 69 | 52 | i-01137e3353fd1341e | 🟢 | 22/22 | running | active | - |
| 70 | 53 | i-0f41f6625543c9360 | 🟢 | 22/22 | running | active | - |
| 71 | 17 | i-07dad225a820393b7 | 🟢 | 22/22 | running | active | - |
| 72 | 54 | i-0f92b3c09e79922af | 🟢 | 22/22 | running | active | - |
| 73 | 55 | i-09fb07752b866b625 | 🟢 | 22/22 | running | active | - |
| 74 | 56 | i-0c741f96535caef83 | 🟢 | 22/22 | running | active | - |
| 75 | 57 | i-0f81a368839d65d30 | 🟢 | 22/22 | running | active | - |
| 76 | 58 | i-081b95b748d8eb4f2 | 🟢 | 22/22 | running | active | - |
| 77 | 59 | i-0cc1e98b0bb51add5 | 🟢 | 22/22 | running | active | - |
| 78 | 60 | i-00273190be23aec75 | 🟢 | 22/22 | running | active | - |
| 79 | 61 | i-0cf78648b808d9b9b | 🟢 | 22/22 | running | active | - |
| 80 | 62 | i-0da9dffb1048b4294 | 🟢 | 22/22 | running | active | - |
| 81 | 63 | i-054d66d7c85838b16 | 🟢 | 22/22 | running | active | - |
| 82 | 18 | i-0c302cfa5355dcccd | 🔴 | 22/22 | running | active | - |
| 83 | 64 | i-0fb9e3ca2de3ec3e3 | 🟢 | 22/22 | running | active | - |
| 84 | 65 | i-016ca794ba164ad11 | 🟢 | 22/22 | running | active | - |
| 85 | 66 | i-0111e6041b043d09a | 🟢 | 22/22 | running | active | - |
| 86 | 67 | i-0dd3109d38676d2b9 | 🟢 | 22/22 | running | active | - |
| 87 | 68 | i-0f47c0b269dc43c63 | 🟢 | 22/22 | running | active | - |
| 88 | 69 | i-009ce00bfaaccadc3 | 🟢 | 22/22 | running | active | - |
| 89 | 70 | i-0dd349bf03fa8aaf8 | 🟢 | 22/22 | running | active | - |
| 90 | 71 | i-052cc9a1a57a00902 | 🟢 | 22/22 | running | active | - |
| 91 | 72 | i-0afef4cbdc107fec8 | 🟢 | 22/22 | running | active | - |
| 92 | 73 | i-0236f38d7c8642c47 | 🟢 | 22/22 | running | active | - |
| 93 | 19 | i-01b68d54ca7fb9943 | 🟢 | 22/22 | running | active | - |
| 94 | 74 | i-05ed8c6f07a22cd40 | 🟢 | 22/22 | running | active | - |
| 95 | 75 | i-0eb833f2f05daffc7 | 🔴 | 22/22 | running | active | - |
| 96 | 76 | i-016b8de10ab5a901e | 🟢 | 22/22 | running | active | - |
| 97 | 77 | i-014c1b7026b5f3b38 | 🟢 | 22/22 | running | active | - |
| 98 | 78 | i-00a0e149de2d91b4c | 🟢 | 22/22 | running | active | - |
| 99 | 79 | i-0618b754c726166b4 | 🟢 | 22/22 | running | active | - |
| 100 | 80 | i-07327d224be13f784 | 🟢 | 22/22 | running | active | - |
| 101 | 81 | i-008b02c2b9b8440d0 | 🟢 | 22/22 | running | active | - |
| 102 | 82 | i-03f905411fb2e06e6 | 🟢 | 22/22 | running | active | - |
| 103 | 83 | i-06f9e170f68b1186b | 🟢 | 22/22 | running | active | - |
| 104 | 20 | i-020c8fdc250ee6c95 | 🟢 | 22/22 | running | active | - |
| 105 | 84 | i-025b36b7359e29121 | 🟢 | 22/22 | running | active | - |
| 106 | 85 | i-0591d2acd4c46c408 | 🟢 | 22/22 | running | active | - |
| 107 | 86 | i-062bf6bbf823a9778 | 🟢 | 22/22 | running | active | - |
| 108 | 87 | i-04b886186bc1aa538 | 🟢 | 22/22 | running | active | - |
| 109 | 88 | i-01772074436038c59 | 🟢 | 22/22 | running | active | - |
| 110 | 89 | i-0b2602434017792a9 | 🟢 | 22/22 | running | active | - |
| 111 | 90 | i-06c85196bfdf8de68 | 🟢 | 22/22 | running | active | - |
| 112 | 91 | i-0f50025d2fb9c7b2a | 🟢 | 22/22 | running | active | - |
| 113 | 92 | i-09e3f0fed2290b2fb | 🟢 | 22/22 | running | active | - |
| 114 | 93 | i-0c2fde36fe4cc79f5 | 🟢 | 22/22 | running | active | - |
| 115 | 21 | i-0ca7f7269d3c043a5 | 🟢 | 22/22 | running | active | - |
| 116 | 94 | i-092e68cd6947c3a0f | 🟢 | 22/22 | running | active | - |
| 117 | 95 | i-002df3a908a6b77dd | 🟢 | 22/22 | running | active | - |
| 118 | 96 | i-0616e40ef110c4a0b | 🟢 | 22/22 | running | active | - |
| 119 | 97 | i-0232255cdd6f4540e | 🟢 | 22/22 | running | active | - |
| 120 | 98 | i-0fae05a192cb61de7 | 🟢 | 22/22 | running | active | - |
| 121 | 99 | i-0ff6d63016347adab | 🟢 | 22/22 | running | active | - |
| 122 | 100 | i-0cd5bff67d72f0533 | 🟢 | 22/22 | running | active | - |
| 123 | 101 | i-057197c656c081d18 | 🟢 | 22/22 | running | active | - |
| 124 | 102 | i-01836736adfad67c1 | 🟢 | 22/22 | running | active | - |
| 125 | 103 | i-0fd5823d845cc3759 | 🟢 | 22/22 | running | active | - |
| 126 | 22 | i-04b50d7d49320a356 | 🟢 | 22/22 | running | active | - |
| 127 | 104 | i-0b75a785b57c781c0 | 🟢 | 22/22 | running | active | - |
| 128 | 105 | i-09b7ddea417dacf74 | 🟢 | 22/22 | running | active | - |
| 129 | 106 | i-052cfcb2d9b163fd0 | 🟢 | 22/22 | running | active | - |
| 130 | 107 | i-0218168d411d2d8ec | 🟢 | 22/22 | running | active | - |
| 131 | 108 | i-00009abb8dfb3a5ab | 🟢 | 22/22 | running | active | - |
| 132 | 109 | i-0c8432c7df68a8e95 | 🟢 | 22/22 | running | active | - |
| 133 | 110 | i-0c688d465d929efbd | 🟢 | 22/22 | running | active | - |
| 134 | 111 | i-0d6acfd224362157f | 🟢 | 22/22 | running | active | - |
| 135 | 112 | i-07d33f83637b76e08 | 🟢 | 22/22 | running | active | - |
| 136 | 113 | i-0ef2920d484b1d941 | 🔴 | 22/22 | running | active | - |
| 137 | 23 | i-05b7661cc7774ddac | 🟢 | 22/22 | running | active | - |
| 138 | 125 | i-033ff8a7840182313 | 🟢 | 22/22 | running | active | - |
