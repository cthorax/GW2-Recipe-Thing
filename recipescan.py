import requests

global profitable_recipes_dict
global processed_item_ingredients_dict
global vendor_items_dict

profitable_recipes_dict = {}
processed_item_ingredients_dict = {}

vendor_items_dict = {
    12157: 8,
    12151: 8,
    12158: 8,
    12153: 8,
    12155: 8,
    12324: 8,
    12136: 8,
    12271: 8,
    62942: 8,
    19704: 8,
    19750: 16,
    19924: 48,
    46747: 150,
    19790: 64,
    19791: 48,
    19793: 32,
    19794: 24,
    19789: 16,
    19792: 8,
    75087: 5000,
    12156: 8,
    75762: 104,
    76839: 56,
    70647: 32,
    13009: 100000,
    13008: 20000,
    13007: 5000,
    13006: 1480,
    13005: 496,
    12235: 2,
    12245: 2,
    12328: 3,
    12141: 2,
    12325: 3,
    12145: 4,
    12152: 2,
    12137: 2,
    12159: 2,
    19717: 21,
    12337: 3,
    12165: 2,
    12340: 3,
    12251: 2,
    12237: 2,
    12338: 3,
    12515: 4,
    12350: 4,
    12256: 1,
    12502: 6,
    12794: 5,
    12518: 4,
    12239: 2,
    12252: 2,
    12339: 3,
    12543: 8,
    12249: 2,
    12503: 6,
    12514: 4,
    12516: 4,
    12517: 4,
    12240: 2

}


def api_query(payload, api_endpoint):

    if api_endpoint == 'recipes_output':
        url = "https://api.guildwars2.com/v2/recipes/search?output={}".format(payload)
    elif api_endpoint == 'recipes_input':
        url = "https://api.guildwars2.com/v2/recipes/search?input={}".format(payload)
    elif api_endpoint == 'recipe_details':
        url = "https://api.guildwars2.com/v2/recipes/{}".format(payload)
    elif api_endpoint == 'api_recipes':
        url = "https://api.guildwars2.com/v2/recipes?access_token={}".format(payload)
    elif api_endpoint == 'item_details':
        url = "https://api.guildwars2.com/v2/items/{}".format(payload)
    elif api_endpoint == 'item_pricing':
        url = "https://api.guildwars2.com/v2/commerce/prices/{}".format(payload)
    else:
        assert False

    result = requests.get(url=url)
    try:
        result.raise_for_status()
        result_dict = result.json()
    except requests.exceptions.HTTPError:
        result_dict = None

    return result_dict


def get_recipes(api=''):
    assert isinstance(api, str)

    recipe_list = api_query(payload=api, api_endpoint='api_recipes')
    return recipe_list


def parse_recipe(recipe_id):
    assert isinstance(recipe_id, int)

    recipe_dict = api_query(payload=recipe_id, api_endpoint='recipe_details')
    return recipe_dict


def parse_item(item_id):
    assert isinstance(item_id, int)

    item_dict = api_query(payload=item_id, api_endpoint='item_details')
    return item_dict


def get_recipe_output(item_id):
    assert isinstance(item_id, int)

    recipe_list = api_query(payload=item_id, api_endpoint='recipes_output')
    return recipe_list


def get_item_price(item_id, listing_type=None):
    assert isinstance(item_id, int)
    assert listing_type in ['buys', 'sells']
    # you BUY instantly from sells and you SELL instantly to buys

    sale_dict = api_query(payload=item_id, api_endpoint='item_pricing')
    if sale_dict:
        price = sale_dict[listing_type]['unit_price']
    elif sale_dict is None:
        price = float('inf')
        if listing_type is 'buys':
            price = -price
        '''
        item_price will be None if the item isn't listed on the trading post.
        since this means the cost for it is infinite, setting the price to infinity is the easiest move.
        '''

    if listing_type is 'sells':
        price = item_from_vendor(item_id=item_id, price=price)
    return price


def item_from_vendor(item_id, price=0):
    try:
        true_price = vendor_items_dict[item_id]
    except LookupError:     # not in vendor items dict
        true_price = price

    return true_price


def get_recipe_price(ingredient_dict, skip_list=[]):
    price = 0
    for item_id, quantity in ingredient_dict.items():
        if item_id in skip_list:
            price = 0
        else:
            try:
                price += quantity * get_item_price(item_id=item_id, listing_type='sells')
            except TypeError:
                pass

    return price


def compare_item_to_ingredients(item, skip_list=[]):
    item_id = item['item_id']
    quantity = item['count']
    cheapest_ingredient_dict = {}

    try:
        cached_ingredient_dict = processed_item_ingredients_dict[item_id]
        for cached_item_id, cached_quantity in cached_ingredient_dict.items():
            cheapest_ingredient_dict[cached_item_id] = quantity * cached_quantity
    except LookupError:     # item not yet in the dict
        output_recipe_list = get_recipe_output(item_id=item_id)
        if output_recipe_list:
            result_price = quantity * get_item_price(item_id=item_id, listing_type='sells')
            cheapest_ingredient_dict = {item_id: quantity}

            # all recipes in the list will be identical crafting discipline specific variants of the same recipe.
            component_recipe_id = output_recipe_list[0]

            cheapest_component_recipe_dict = base_recipe_list(recipe_input=component_recipe_id)

            component_total_price = 0
            for component_item_id, component_quantity in cheapest_component_recipe_dict.items():
                component_item_price = get_item_price(item_id=component_item_id, listing_type='sells')
                component_total_price += component_item_price * component_quantity

            if skip_list:
                for skip_item_id in skip_list:
                    if skip_item_id in cheapest_component_recipe_dict.keys():
                        cheapest_ingredient_dict = cheapest_component_recipe_dict
                        processed_item_ingredients_dict[item_id] = cheapest_ingredient_dict

            else:
                if component_total_price < result_price:
                    cheapest_ingredient_dict = cheapest_component_recipe_dict
                    processed_item_ingredients_dict[item_id] = cheapest_ingredient_dict

        else:
            cheapest_ingredient_dict[item_id] = quantity
            processed_item_ingredients_dict[item_id] = {item_id: 1}

    return cheapest_ingredient_dict


def base_recipe_list(recipe_input, skip_list=[]):
    if isinstance(recipe_input, int):
        recipe_dict = parse_recipe(recipe_id=recipe_input)
    elif isinstance(recipe_input, dict):
        recipe_dict = recipe_input
    ingredient_list = recipe_dict['ingredients']

    cleaned_ingredient_dict = {}
    for item in ingredient_list:
        single_item_dict = compare_item_to_ingredients(item=item, skip_list=skip_list)
        for item_id, quantity in single_item_dict.items():
            if item_id in cleaned_ingredient_dict:
                cleaned_ingredient_dict[item_id] += quantity
            else:
                cleaned_ingredient_dict[item_id] = quantity

    return cleaned_ingredient_dict


def get_recipe_profit_from_id(recipe_id, min_profit=0):
    recipe_dict = parse_recipe(recipe_id=recipe_id)
    output_item_id = recipe_dict['output_item_id']
    output_quantity = recipe_dict['output_item_count']
    output_sale_price = get_item_price(item_id=output_item_id, listing_type='buys') * output_quantity

    if output_sale_price >= min_profit:
        ingredient_dict = base_recipe_list(recipe_input=recipe_dict)
        ingredient_price = get_recipe_price(ingredient_dict=ingredient_dict)
        result = output_sale_price - ingredient_price
    else:
        result = -float('inf')

    return result


def get_recipe_profit_from_dicts(recipe_dict, ingredient_dict, skip_list=[], min_profit=0):
    output_item_id = recipe_dict['output_item_id']
    output_quantity = recipe_dict['output_item_count']
    output_sale_price = get_item_price(item_id=output_item_id, listing_type='buys') * output_quantity

    if output_sale_price >= min_profit:
        ingredient_price = get_recipe_price(ingredient_dict=ingredient_dict, skip_list=skip_list)
        result = output_sale_price - ingredient_price
    else:
        result = -float('inf')

    return result

def get_profitable_recipes(recipes_list, min_profit=1000, verbose=False):
    for recipe_id in recipes_list:
        profit = get_recipe_profit_from_id(recipe_id, min_profit=min_profit)
        if profit > min_profit and not profit == float('inf') and not profit == -float('inf'):
            profitable_recipes_dict[recipe_id] = profit
            output_recipe({recipe_id: profit})
            profitable_recipes_dict[recipe_id] = profit
        elif verbose:
            print('''--------------------------
Recipe ID: {recipe}
not profitable'''.format(recipe=recipe_id))

    return profitable_recipes_dict


def output_recipe(profit_dict, force_output=False):
    output_string = '''--------------------------
Recipe ID: {recipe}
Item: {name}

Ingredients:
{ingredients}
Sale price:\t\t\t{price}
Ingredients cost:\t{ingredients_cost}
Profit per item:\t{profit}

ROI: {roi:.3%}'''

    recipe_id = profit_dict.get('recipe', None)
    ingredients_dict = profit_dict.get('ingredients', None)

    recipe_dict = parse_recipe(recipe_id)
    output_item_id = recipe_dict['output_item_id']
    output_item_price = get_item_price(item_id=output_item_id, listing_type='buys')

    if ingredients_dict is None:
        ingredients_dict = base_recipe_list(recipe_id)
    ingredients_string = ''
    ingredients_price = 0

    if recipe_id:   # if this is None, it means we're just selling the item, and thus there's no ingredients and they cost nothing.
        for temp_id, temp_quantity in ingredients_dict.items():
            temp_price = get_item_price(item_id=temp_id, listing_type='sells')
            temp_total = temp_price * temp_quantity
            ingredients_price += temp_total
            temp_item_dict = parse_item(item_id=temp_id)
            temp_name = temp_item_dict['name']
            ingredients_string = ''.join([ingredients_string, '{quantity} {name} at {price} ({total_price})\n'.format(quantity=temp_quantity, name=temp_name, price=format_prices(temp_price), total_price=format_prices(temp_total))])

    rechecked_profit = output_item_price - ingredients_price
    if rechecked_profit <= 0 and not force_output:
        return

    item_dict = parse_item(output_item_id)
    item_name = item_dict['name']

    roi = rechecked_profit / ingredients_price
    profit_string = format_prices(rechecked_profit)
    cost_string = format_prices(ingredients_price)
    price_string = format_prices(output_item_price)

    print(output_string.format(recipe=recipe_id, name=item_name, ingredients=ingredients_string, price=price_string, ingredients_cost=cost_string, profit=profit_string, roi=roi))
    return


def format_prices(price):
    try:
        price = int(price)
        copper = price % 100
        silver = (price % 10000) // 100
        gold = price // 10000

        if gold:
            price_string = '{g}g {s}s {c}c'.format(g=gold, s=silver, c=copper)
        elif silver:
            price_string = '{s}s {c}c'.format(s=silver, c=copper)
        else:
            price_string = '{c}c'.format(c=copper)
    except OverflowError:   # 'cannot convert float infinity to integer', happens when price = inf
        price_string = 'infinite'
    except ValueError:      # 'cannot convert float NaN to integer', happens when passed inf/x
        price_string = 'infinite'

    return price_string


def get_all_successor_recipes_from_item(item_id):
    stage_one_recipe_list = api_query(payload=item_id, api_endpoint='recipes_input')
    master_recipe_set = set(get_all_successor_recipes_from_recipe_list(stage_one_recipe_list))
    return list(master_recipe_set)


def get_all_successor_recipes_from_recipe_list(recipe_list, verbose=False):
    if not recipe_list:
        return []
    else:
        master_recipe_set = set(recipe_list)

        if verbose:
            print('\ncurrent set: {recipe_set}'.format(recipe_set=master_recipe_set))
        for recipe_id in recipe_list:
            recipe_dict = api_query(payload=recipe_id, api_endpoint='recipe_details')
            output_item_id = recipe_dict['output_item_id']
            current_tier_recipe_list = api_query(payload=output_item_id, api_endpoint='recipes_input')
            master_recipe_set.update(current_tier_recipe_list)

            if verbose:
                print('recipe {recipe_id}: will add {current_list} to set. beginning recursion.'.format(recipe_id=recipe_id, current_list=current_tier_recipe_list))

            next_tier_recipe_list = get_all_successor_recipes_from_recipe_list(recipe_list=current_tier_recipe_list)
            master_recipe_set.update(next_tier_recipe_list)

        return list(master_recipe_set)


def best_recipe_for_item(item_id, target_item_id=None, recursion_depth=0, skip_list=[], verbose=True):
    if target_item_id is None:
        target_item_id = item_id

    best_list = []

    if verbose:
        recursion_buffer = '\t' * recursion_depth
        item_name = api_query(payload=item_id, api_endpoint='item_details').get('name')
        print('{recurse}{item_name}'.format(item_name=item_name, recurse=recursion_buffer))

    recipe_list = api_query(payload=item_id, api_endpoint='recipes_input')

    for recipe_id in recipe_list:
        recipe_dict = api_query(payload=recipe_id, api_endpoint='recipe_details')
        output_item_id = recipe_dict['output_item_id']
        intermediate_skip_list = skip_list.copy()
        intermediate_skip_list.append(item_id)
        recipe_ingredient_dict = base_recipe_list(recipe_input=recipe_dict, skip_list=intermediate_skip_list)

        target_item_count = recipe_ingredient_dict.get(target_item_id, 0)
        if target_item_count > 0:
            best_list.append({'recipe': recipe_id, 'ingredients': recipe_ingredient_dict})

        if verbose:
            print('{recurse}recursion beginning!'.format(recurse=recursion_buffer))
        recursion = best_recipe_for_item(item_id=output_item_id, target_item_id=target_item_id, recursion_depth=recursion_depth+1, skip_list=skip_list)

        if recursion:
            best_list.extend(recursion)

        if verbose:
            print('{recurse}recursion ending!'.format(recurse=recursion_buffer))

    return best_list


def testing(function_to_test, function_input=None, expected=None):

    if function_input:
        result = function_to_test(function_input)
    else:
        result = function_to_test()

    if result == expected:
        test = True
    else:
        test = False

    return test


def main():
    pass


if __name__ == '__main__':
    main()

    material_storage = [
    12134,
    12238,
    12147,
    12142,
    12135,
    12246,
    12255,
    12163,
    12165,
    12236,
    12240,
    12331,
    12258,
    12256,
    12232,
    12252,
    12249,
    12248,
    12141,
    12234,
    12138,
    12137,
    12159,
    12143,
    12152,
    24359,
    24360,
    12136,
    12158,
    12151,
    12153,
    12271,
    12324,
    12155,
    12157,
    12156,
    12253,
    12161,
    12327,
    12244,
    12243,
    12241,
    12162,
    12145,
    12251,
    12245,
    12247,
    12235,
    12237,
    12239,
    12250,
    12229,
    12332,
    12336,
    12341,
    12333,
    12334,
    12335,
    12342,
    12329,
    12330,
    12337,
    12340,
    12338,
    12328,
    12339,
    12325,
    12537,
    12532,
    12534,
    12531,
    12533,
    12536,
    12535,
    12538,
    12515,
    12350,
    12518,
    12351,
    12514,
    12516,
    12517,
    12512,
    12505,
    12511,
    12504,
    12508,
    12507,
    12254,
    12506,
    12510,
    12509,
    12144,
    12502,
    12503,
    12545,
    12544,
    12546,
    12128,
    12547,
    12543,
    36731,
    66524,
    66522,
    73113,
    74242,
    74266,
    73096,
    73504,
    81837,
    82991,
    82866,
    82806,
    84696,
    83195
  ]
    for main_item_id in material_storage:

        item_dict = parse_item(item_id=main_item_id)
        name = item_dict['name']
        print('{}:'.format(name.upper()))
        best_profit_list = best_recipe_for_item(item_id=main_item_id, skip_list=[main_item_id], verbose=True)
        for recipe_dict in best_profit_list:
            output_recipe(best_profit_dict)

