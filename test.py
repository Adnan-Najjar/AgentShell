import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt 
import json
from main import * 

def levenshtein_distance(s1: str, s2: str) -> int:
    """
    Calculate the Levenshtein distance between two strings using O(min(n,m)) memory.
    """
    if len(s1) < len(s2):
        s1, s2 = s2, s1  # Ensure s1 is the longer string
    
    previous_row = list(range(len(s2) + 1))
    
    for i, c1 in enumerate(s1, 1):
        current_row = [i]
        for j, c2 in enumerate(s2, 1):
            insertions = previous_row[j] + 1
            deletions = current_row[j - 1] + 1
            substitutions = previous_row[j - 1] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    
    return previous_row[-1]


def levenshtein_l_ratio(s1: str, s2: str) -> float:
    """
    Calculate the L-ratio similarity between two strings.
    """
    n = len(s1)
    m = len(s2)
    lev = levenshtein_distance(s1, s2)
    max_len = max(n, m)
    
    if max_len == 0:
        return 1.0
    
    l_ratio = (max_len - lev) / max_len
    return l_ratio

def create_llm_data(commands: list) -> int:
    output = {}
    total_tokens = 0
    for command in commands:
        response, tokens = get_llm_response(command)
        output[command] = response
        total_tokens += tokens
        print("Command: ", command, "\nTokens used: ", tokens)

    with open("data/llm.json", 'w') as f:
        json.dump(output, f, indent=2)

    return total_tokens

# Test cases
if __name__ == "__main__":
    with open('data/commands.txt', 'r') as f:
        commands = [line.strip() for line in f if line.strip()]
    
    tokens_used = create_llm_data(commands)

    vm = json.load(open('data/vm.json', 'r'))
    cowrie = json.load(open('data/cowrie.json', 'r'))
    llm = json.load(open('data/llm.json', 'r'))

    category = json.load(open('categories.json', 'r'))
    cowrie_system = []
    cowrie_filesystem = []
    cowrie_connectivity = []

    llm_system = []
    llm_filesystem = []
    llm_connectivity = []
    
    for command in commands:
        print(command)
        cowrie_lev = levenshtein_l_ratio(cowrie[command], vm[command])
        llm_lev = levenshtein_l_ratio(llm[command], vm[command])
        
        if category[command] == "#780ee":  # Filesystem
            cowrie_filesystem.append(cowrie_lev)
            llm_filesystem.append(llm_lev)
        elif category[command] == "#f7a60":  # System
            cowrie_system.append(cowrie_lev)
            llm_system.append(llm_lev)
        elif category[command] == "#46c52":  # Connectivity
            cowrie_connectivity.append(cowrie_lev)
            llm_connectivity.append(llm_lev)

    # Create scatter plot with different colors for each category
    plt.figure(figsize=(10, 8))
    plt.scatter(cowrie_filesystem, llm_filesystem, c='purple', label='Filesystem', alpha=0.7)
    plt.scatter(cowrie_system, llm_system, c='orange', label='System', alpha=0.7)
    plt.scatter(cowrie_connectivity, llm_connectivity, c='green', label='Connectivity', alpha=0.7)
    
    plt.xlabel("Cowrie L-Ratio")
    plt.ylabel("LLM L-Ratio")
    plt.title("Command Similarity: Cowrie vs LLM")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.plot([0, 1], [0, 1], 'k--', alpha=0.5)  # Diagonal line for perfect correlation
    
    # Add statistics
    plt.text(0.02, 0.98, f"Total commands: {len(commands)}", transform=plt.gca().transAxes, 
             verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    plt.tight_layout()
    
    # Save the plot
    plt.savefig('results/similarity_plot.png', dpi=300, bbox_inches='tight')
    
    # Calculate averages
    def average(lst):
        return sum(lst) / len(lst) if lst else 0
    
    cowrie_avg = average(cowrie_system + cowrie_filesystem + cowrie_connectivity)
    llm_avg = average(llm_system + llm_filesystem + llm_connectivity)
    
    cowrie_system_avg = average(cowrie_system)
    llm_system_avg = average(llm_system)
    
    cowrie_filesystem_avg = average(cowrie_filesystem)
    llm_filesystem_avg = average(llm_filesystem)
    
    cowrie_connectivity_avg = average(cowrie_connectivity)
    llm_connectivity_avg = average(llm_connectivity)
    
    # Create markdown content
    markdown_content = f"""# Command Similarity Analysis

## Scatter Plot

![Command Similarity Scatter Plot](similarity_plot.png)

## Results Table

| L-ratio | Cowrie | LLM |
|---------|--------|-----|
| Average | {cowrie_avg:.3f} | {llm_avg:.3f} |
| System Average | {cowrie_system_avg:.3f} | {llm_system_avg:.3f} |
| Filesystem Average | {cowrie_filesystem_avg:.3f} | {llm_filesystem_avg:.3f} |
| Connectivity Average | {cowrie_connectivity_avg:.3f} | {llm_connectivity_avg:.3f} |

## Summary

- Total commands analyzed: {len(commands)}
- System commands: {len(cowrie_system)}
- Filesystem commands: {len(cowrie_filesystem)}
- Connectivity commands: {len(cowrie_connectivity)}
- Tokens used: {tokens_used}
"""
    
    # Save to results.md
    with open('results/results.md', 'w') as f:
        f.write(markdown_content)
    
    print("Results saved in results directory")
