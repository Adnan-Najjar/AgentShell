# Believability Analysis

## Commands

| Category | control | cowrie | llama3-1-8k | agentshell | shellbox | decoypot | low-risk |
| --- | --- | --- | --- | --- | --- | --- | --- |
| connectivity | 100% | 60% | 76% | 80% | 68% | 80% | 80% |
| filesystem | 100% | 58% | 83% | 83% | 97% | 75% | 92% |
| system | 100% | 55% | 76% | 85% | 45% | 82% | 85% |
| **Overall** | **100%** | **57%** | **79%** | **83%** | **71%** | **79%** | **86%** |

## Scenarios

| Scenario | control | cowrie | llama3-1-8k | agentshell | shellbox | decoypot | low-risk |
| --- | --- | --- | --- | --- | --- | --- | --- |
| system_reconnaissance | 100% | 78% | 100% | 100% | 89% | 100% | 100% |
| scanning_lateral_propagation | 100% | 56% | 89% | 67% | 78% | 67% | 78% |
| persistence | 100% | 44% | 78% | 89% | 78% | 78% | 44% |
| data_reconnaissance_exfiltration | 100% | 44% | 89% | 67% | 89% | 78% | 67% |
| data_obfuscation_ransomware | 100% | 89% | 100% | 89% | 78% | 78% | 78% |
| **Overall** | **100%** | **62%** | **91%** | **82%** | **82%** | **80%** | **73%** |

## Token Usage

| Tactic | control | cowrie | llama3-1-8k | agentshell | shellbox | decoypot | low-risk |
| --- | --- | --- | --- | --- | --- | --- | --- |
| system_reconnaissance | 0 | 0 | 10191 | 33465 | 28449 | 15794 | 27139 |
| scanning_lateral_propagation | 0 | 0 | 10883 | 28427 | 27867 | 12596 | 3275 |
| persistence | 0 | 0 | 8636 | 18874 | 14865 | 13420 | 1059 |
| data_reconnaissance_exfiltration | 0 | 0 | 11376 | 21944 | 14170 | 14765 | 1123 |
| data_obfuscation_ransomware | 0 | 0 | 11382 | 14296 | 14264 | 14386 | 1586 |
| **Total** | **0** | **0** | **52468** | **117006** | **99615** | **70961** | **34182** |

## Bar Chart

![Believability Bar Chart](result_bar.png)

## Token Charts

### System Reconnaissance
![system_reconnaissance Tokens](result_tokens_system_reconnaissance.png)

### Scanning Lateral Propagation
![scanning_lateral_propagation Tokens](result_tokens_scanning_lateral_propagation.png)

### Persistence
![persistence Tokens](result_tokens_persistence.png)

### Data Reconnaissance Exfiltration
![data_reconnaissance_exfiltration Tokens](result_tokens_data_reconnaissance_exfiltration.png)

### Data Obfuscation Ransomware
![data_obfuscation_ransomware Tokens](result_tokens_data_obfuscation_ransomware.png)

