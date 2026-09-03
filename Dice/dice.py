import random

def roll_dice(nums=1,sides=6):
    """
    Rolls a dice with the specified number of sides and returs the result.
    """
    if nums < 1:
        raise ValueError("Number of dice must be at least 1.")
    if sides < 2:
        raise ValueError("Number of sides must be at least 2.")
    
    results = [random.randint(1, sides) for _ in range(nums)]
    return results

def main():
    nums = int(input("Enter the number of dice to roll: "))
    sides = int(input("Enter the number of sides on the dice: "))
    results = roll_dice(nums, sides)
    print(f"Results: {results}")

if __name__ == "__main__":
    main()