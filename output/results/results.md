# Believability Analysis

## Commands

| Category | control | cowrie | llama3-1-8k | agentshell | shellbox | low-risk |
| --- | --- | --- | --- | --- | --- | --- |
| connectivity | 100% | 60% | 84% | 80% | 68% | 80% |
| filesystem | 100% | 56% | 89% | 83% | 97% | 92% |
| system | 100% | 55% | 94% | 85% | 45% | 85% |
| **Overall** | **100%** | **56%** | **89%** | **83%** | **71%** | **86%** |

## Scenarios

| Scenario | control | cowrie | llama3-1-8k | agentshell | shellbox | low-risk |
| --- | --- | --- | --- | --- | --- | --- |
| system_reconnaissance | 100% | 78% | 89% | 100% | 89% | 100% |
| scanning_lateral_propagation | 100% | 56% | 67% | 67% | 67% | 67% |
| persistence | 100% | 44% | 56% | 89% | 78% | 44% |
| data_reconnaissance_exfiltration | 100% | 44% | 89% | 56% | 89% | 67% |
| data_obfuscation_ransomware | 100% | 89% | 89% | 89% | 78% | 78% |
| **Overall** | **100%** | **62%** | **78%** | **80%** | **80%** | **71%** |

## Token Usage

| Tactic | control | cowrie | llama3-1-8k | agentshell | shellbox | low-risk |
| --- | --- | --- | --- | --- | --- | --- |
| system_reconnaissance | 0 | 0 | 8271 | 33465 | 28449 | 27139 |
| scanning_lateral_propagation | 0 | 0 | 9828 | 28427 | 27867 | 3275 |
| persistence | 0 | 0 | 7433 | 18874 | 14865 | 1059 |
| data_reconnaissance_exfiltration | 0 | 0 | 9115 | 21944 | 14170 | 1123 |
| data_obfuscation_ransomware | 0 | 0 | 10594 | 14296 | 14264 | 1586 |
| **Total** | **0** | **0** | **45241** | **117006** | **99615** | **34182** |

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

