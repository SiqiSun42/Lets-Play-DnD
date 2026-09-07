def init_order(allies_nums, allies_names, enemies_nums, enemies_names, all_nums, initiative_dice):
    '''
    将先攻骰子值和每个参与者匹配
    '''
    if allies_nums + enemies_nums != all_nums:
        return "ERROR"

    if len(initiative_dice) != all_nums:
        return "ERROR"

    res = ["团队的先攻骰子值: "]
    for i in range(all_nums):
        dice = str(initiative_dice[i])
        if i < allies_nums:
            name = allies_names[i]
            res.append(name + ": " + dice)
        else:
            if i == allies_nums:
                res.append("敌人的先攻骰子值: ")
            name = enemies_names[i - allies_nums]
            res.append(name + ": " + dice)

    output = "\n".join(res)
    return output

def main():
    allies_names = ["A", "B"]
    enemies_names = ["C", "D", "E"]
    output = init_order(2, allies_names, 3, enemies_names, 5, [1, 2, 3, 4, 5])
    print(output)

if __name__ == "__main__":
    main()