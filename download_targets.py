from dataset_manager.scripts.cli import _do_download, load_config
from dataset_manager.database.db import get_dataset_by_name

config = load_config()
targets = ['mext_food_composition_2023', 'usda_fooddata_central', 'usda_foodkeeper']

for ds_config in config.get('datasets', []):
    name = ds_config['name']
    if name in targets:
        row = get_dataset_by_name(name)
        if row:
            print(f'Downloading {name}')
            try:
                _do_download(ds_config, row['id'])
            except Exception as e:
                print(f'Failed {name}: {e}')
        else:
            print(f'Row for {name} not found in DB.')
