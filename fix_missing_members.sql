-- Fix Missing Member Records for Existing Users
-- This script creates Member records for users who have accounts but no member profile

DO $$
DECLARE
    v_user_id INT;
    v_username TEXT;
    v_last_member_code TEXT;
    v_next_member_code TEXT;
    v_code_number INT;
BEGIN
    -- Loop through all users with role 'member' who don't have a member record
    FOR v_user_id, v_username IN
        SELECT u.id, u.username
        FROM users u
        LEFT JOIN members m ON m.user_id = u.id
        WHERE u.role = 'member' 
          AND u.is_active = true
          AND m.id IS NULL
    LOOP
        -- Get the last member code to generate next sequential code
        SELECT member_code INTO v_last_member_code
        FROM members
        ORDER BY id DESC
        LIMIT 1;
        
        -- Generate next member code
        IF v_last_member_code IS NULL THEN
            v_next_member_code := 'MEM0001';
        ELSE
            -- Extract number from last code (e.g., 'MEM0005' -> 5)
            v_code_number := CAST(SUBSTRING(v_last_member_code FROM 4) AS INT);
            -- Increment and format (e.g., 6 -> 'MEM0006')
            v_next_member_code := 'MEM' || LPAD((v_code_number + 1)::TEXT, 4, '0');
        END IF;
        
        -- Create member record
        INSERT INTO members (user_id, member_code, monthly_amount, status, address)
        VALUES (v_user_id, v_next_member_code, 0.0, 'active', NULL);
        
        RAISE NOTICE 'Created member record for user ID % (username: %) with code %', 
                     v_user_id, v_username, v_next_member_code;
    END LOOP;
    
    -- Summary
    RAISE NOTICE 'Migration complete. Check if any member records were created above.';
END $$;

-- Verify the fix
SELECT 
    u.id as user_id,
    u.username,
    u.email,
    m.id as member_id,
    m.member_code,
    m.status
FROM users u
LEFT JOIN members m ON m.user_id = u.id
WHERE u.role = 'member'
ORDER BY u.id;
