import os

for r, d, fs in os.walk('dataset_manager'):
    for f in fs:
        if f.endswith('.py'):
            fp = os.path.join(r, f)
            with open(fp, 'r', encoding='utf-8') as file:
                content = file.read()
            
            # The tool might have inserted literally `\"\"\"`
            if r'\"\"\"' in content:
                new_content = content.replace(r'\"\"\"', '\"\"\"')
                with open(fp, 'w', encoding='utf-8') as file:
                    file.write(new_content)
                print(f"Fixed {fp}")
